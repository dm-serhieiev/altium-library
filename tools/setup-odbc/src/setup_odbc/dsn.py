"""User DSN inspection, narrowly scoped installer calls and verified rollback."""

from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterator

from .database import equivalent_path
from .drivers import Driver, registry_values
from .errors import SetupError
from .odbc import connection_string, verify_connection

DSN_NAME = "AltiumComponents"
UNSAFE_OPTIONS = ("tracefile", "loadext", "attachas", "journalmode", "syncpragma")


@dataclass(frozen=True)
class Dsn:
    driver: str | None
    attributes: dict[str, str] | None


def read_dsn(name: str, driver: Driver) -> Dsn | None:
    base = r"SOFTWARE\ODBC\ODBC.INI"
    records = {}
    for scope in ("System", "User"):
        for bits in (64, 32):
            names = registry_values(scope, base + r"\ODBC Data Sources", bits) or {}
            attrs = registry_values(scope, base + "\\" + name, bits)
            registered = names.get(name.casefold())
            if attrs is not None or registered is not None:
                records[scope, bits] = Dsn(registered, attrs)
    if not records:
        return None
    user = records.get(("User", 64))
    conflict = (any(scope == "System" for scope, _ in records) or user is None or
                any(record != user for record in records.values()))
    if not conflict:
        conflict = (user.driver is None or user.driver.casefold() != driver.name.casefold() or
                    user.attributes is None or
                    not equivalent_path(user.attributes.get("driver"), driver.dll))
    if conflict:
        raise SetupError(f"Conflicting DSN '{name}': expected a compatible 64-bit User DSN. "
                         "Resolve incompatible User/System registrations explicitly in ODBC Data Sources.")
    for key in UNSAFE_OPTIONS:
        if user.attributes.get(key, "").strip():
            raise SetupError(f"Conflicting DSN option '{key}' in '{name}'. Resolve it in ODBC Data Sources.")
    return user


class Installer:
    """Documented ODBC installer APIs only; no registry writes or subprocesses."""

    def __init__(self):
        self.api = c.WinDLL("odbccp32")
        signatures = {
            "SQLConfigDataSourceW": [wintypes.HWND, wintypes.WORD, wintypes.LPCWSTR, wintypes.LPCWSTR],
            "SQLWritePrivateProfileStringW": [wintypes.LPCWSTR] * 4,
            "SQLGetConfigMode": [c.POINTER(wintypes.WORD)],
            "SQLSetConfigMode": [wintypes.WORD],
        }
        for name, args in signatures.items():
            fn = getattr(self.api, name)
            fn.argtypes, fn.restype = args, wintypes.BOOL

    def _config(self, request: int, name: str, driver: Driver, attributes: dict[str, str]) -> None:
        values = {"DSN": name, **attributes}
        if any("\0" in key or "\0" in value for key, value in values.items()):
            raise SetupError("Invalid ODBC installer attribute.")
        buffer = c.create_unicode_buffer("\0".join(f"{key}={value}" for key, value in values.items()) + "\0\0")
        if not self.api.SQLConfigDataSourceW(None, request, driver.name, buffer):
            raise SetupError(f"ODBC configuration failed for '{name}'. Check User DSN permissions and driver installation.")

    def create(self, name: str, driver: Driver) -> None:
        # Some SQLite builds expose only ANSI ConfigDSN. Pass ASCII setup values;
        # write the Unicode path through the installer's W profile API separately.
        self._config(1, name, driver, {"NoCreat": "1"})

    def remove(self, name: str, driver: Driver) -> None:
        self._config(3, name, driver, {})

    def database(self, name: str, value: str | None) -> None:
        mode = wintypes.WORD()
        if not self.api.SQLGetConfigMode(c.byref(mode)) or not self.api.SQLSetConfigMode(1):
            raise SetupError("ODBC configuration failed: cannot select User DSN scope.")
        try:
            # None deletes just this attribute, restoring original absence.
            if not self.api.SQLWritePrivateProfileStringW(name, "Database", value, "ODBC.INI"):
                raise SetupError(f"ODBC configuration failed while setting Database for '{name}'.")
        finally:
            if not self.api.SQLSetConfigMode(mode.value):
                raise SetupError("ODBC configuration failed: cannot restore installer scope.")


@contextmanager
def setup_lock(name: str) -> Iterator[None]:
    """Serialize this application's instances. Never block on an abandoned run."""
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [c.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.ReleaseMutex.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateMutexW(None, False, "Local\\AltiumOdbcSetup-" + name)
    if not handle:
        raise SetupError("Cannot acquire the ODBC setup lock. Check Windows permissions.")
    acquired = False
    try:
        result = kernel.WaitForSingleObject(handle, 0)
        acquired = result in (0, 0x80)  # WAIT_OBJECT_0 or WAIT_ABANDONED
        if result == 0x80:
            raise SetupError("A previous ODBC setup was interrupted. Inspect the DSN and retry.")
        if not acquired:
            raise SetupError("Another ODBC setup is running or the setup lock is unavailable. Retry after it finishes.")
        yield
    finally:
        if acquired:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def _with_database(previous: Dsn, value: str) -> Dsn:
    return replace(previous, attributes={**previous.attributes, "database": value})


def configure(name: str, driver: Driver, path: Path, *, check_only: bool = False) -> str:
    """Caller owns the guarded snapshot. Read-back precedes connection testing."""
    connection_string(name, path)  # validate internal name even when mocked
    with setup_lock(name):
        previous = read_dsn(name, driver)
        same = previous is not None and equivalent_path(previous.attributes.get("database"), path)
        if check_only and not same:
            raise SetupError(f"DSN '{name}' is missing or points to another database. Run without --check-only. No changes made.")
        if same:
            verify_connection(name, path)
            if read_dsn(name, driver) != previous:
                raise SetupError("DSN changed concurrently during verification. No changes made by setup.")
            return "Already configured. No changes required."

        installer = Installer()
        expected = None
        attempted = False
        # An ASCII-only create has a precisely known intermediate state. If a
        # driver adds unfamiliar settings, fail closed instead of deleting them.
        created = Dsn(driver.name, {"driver": driver.dll, "nocreat": "1"})
        try:
            if read_dsn(name, driver) != previous:
                raise SetupError("DSN changed concurrently before configuration. No changes made.")
            attempted = True
            if previous is None:
                expected = created
                installer.create(name, driver)
                if read_dsn(name, driver) != expected:
                    raise SetupError("ODBC configuration read-back failed after DSN creation.")
            expected = _with_database(previous or created, str(path))
            installer.database(name, str(path))
            if read_dsn(name, driver) != expected:
                raise SetupError("ODBC configuration read-back failed: expected settings were not retained.")
            verify_connection(name, path)
            if read_dsn(name, driver) != expected:
                raise SetupError("DSN changed concurrently during verification.")
        except (Exception, KeyboardInterrupt) as exc:
            failure = str(exc) if isinstance(exc, SetupError) else "Unexpected ODBC configuration failure."
            if attempted:
                try:
                    current = read_dsn(name, driver)
                    if current == previous:
                        pass  # failed before mutation, or settings already restored
                    elif current not in (expected, created if previous is None else previous):
                        raise SetupError("DSN changed concurrently; not overwriting it.")
                    elif previous is None:
                        installer.remove(name, driver)
                    else:
                        installer.database(name, previous.attributes.get("database"))
                    if read_dsn(name, driver) != previous:
                        raise SetupError("Rollback read-back mismatch.")
                    failure += (" Newly created DSN removed." if previous is None
                                else " Previous DSN database setting restored.")
                except Exception:
                    failure += f" Rollback incomplete; inspect '{name}' in ODBC Data Sources. Concurrent settings were not overwritten."
            raise SetupError(failure) from exc
        return "New User DSN created." if previous is None else "Existing DSN updated."
