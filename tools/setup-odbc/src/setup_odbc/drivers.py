"""Read-only inspection of Windows ODBC registrations in both registry views."""

import ctypes
from dataclasses import dataclass
import ntpath
import os
from pathlib import PureWindowsPath
import sys

from .errors import SetupError

DEFAULT_DRIVER = "SQLite3 ODBC Driver"


def require_windows_x64() -> None:
    if sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise SetupError("64-bit Windows is required. Run the Windows x64 setup-odbc.exe "
                         "(or use 64-bit Python 3.11+ for source execution).")


def registry_values(hive: str, path: str, bits: int, *, text_only: bool = True) -> dict[str, str] | None:
    """None means the key is absent, never a failed inspection. Keys casefolded."""
    import winreg

    root = winreg.HKEY_CURRENT_USER if hive == "User" else winreg.HKEY_LOCAL_MACHINE
    view = winreg.KEY_WOW64_64KEY if bits == 64 else winreg.KEY_WOW64_32KEY
    try:
        key = winreg.OpenKey(root, path, 0, winreg.KEY_READ | view)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SetupError("Cannot inspect Windows ODBC registration. Check registry read permissions.") from exc
    try:
        with key:
            result = {}
            for i in range(winreg.QueryInfoKey(key)[1]):
                name, value, kind = winreg.EnumValue(key, i)
                if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) or not isinstance(value, str):
                    if not text_only:
                        continue  # Driver metadata includes a DWORD UsageCount.
                    raise SetupError("Conflicting ODBC registration: non-text setting. Inspect ODBC Data Sources.")
                if "\0" in value:
                    raise SetupError("Conflicting ODBC registration: embedded null in a setting.")
                if kind == winreg.REG_EXPAND_SZ and text_only:
                    # Installer profile writes use REG_SZ. Do not silently lose
                    # an original DSN value's type/expansion semantics on rollback.
                    raise SetupError("Conflicting ODBC registration: expandable setting. Inspect ODBC Data Sources.")
                result[name.casefold()] = os.path.expandvars(value) if kind == winreg.REG_EXPAND_SZ else value
            return result
    except OSError as exc:
        raise SetupError("Cannot inspect Windows ODBC settings. Check registry read permissions.") from exc


@dataclass(frozen=True)
class Driver:
    name: str
    bits: int
    dll: str


def installed_drivers() -> list[Driver]:
    result = []
    base = r"SOFTWARE\ODBC\ODBCINST.INI"
    for bits in (64, 32):
        names = registry_values("System", base + r"\ODBC Drivers", bits) or {}
        for name, installed in names.items():
            if "sqlite" not in name or installed.casefold() != "installed":
                continue
            attrs = registry_values("System", base + "\\" + name, bits, text_only=False)
            if attrs is None:
                raise SetupError(f"Incomplete SQLite driver registration ({bits}-bit). Inspect ODBC Data Sources.")
            # Registry lookup is case-insensitive; preserve the public default spelling.
            display = DEFAULT_DRIVER if name == DEFAULT_DRIVER.casefold() else name
            result.append(Driver(display, bits, attrs.get("driver", "")))
    return result


def select_driver(name: str, drivers: list[Driver]) -> Driver:
    if not name.strip() or "sqlite" not in name.casefold() or any(c in name for c in "*?[];\0\r\n"):
        raise SetupError("Driver name must be the exact installed name of a compatible SQLite3 ODBC driver, without wildcards.")
    selected = [d for d in drivers if d.bits == 64 and d.name.casefold() == name.casefold()]
    if len(selected) != 1:
        raise SetupError(f"Required 64-bit driver '{name}' is unavailable. Install the trusted SQLite3 x64 "
                         "driver (sqliteodbc_w64.exe from https://www.ch-werner.de/sqliteodbc/) separately.")
    driver = selected[0]
    if ntpath.basename(driver.dll).casefold() != "sqlite3odbc.dll" or not PureWindowsPath(driver.dll).is_absolute():
        raise SetupError(f"Selected driver '{name}' is not the supported SQLite3 ODBC implementation (sqlite3odbc.dll).")
    return driver
