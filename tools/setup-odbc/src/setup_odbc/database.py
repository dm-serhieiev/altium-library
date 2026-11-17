"""Locate and hold an existing SQLite snapshot without permitting writes."""

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import ntpath
import os
from pathlib import Path, PureWindowsPath
import stat
import sys
from typing import Iterator, BinaryIO
from urllib.parse import quote

from .errors import SetupError


def database_path() -> Path:
    tools = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
             else Path(__file__).resolve().parents[3])
    return (tools.parent / "database" / "components.sqlite").resolve()


def equivalent_path(left: str | None, right: str | Path) -> bool:
    # Fully qualified drive/UNC paths only. Never interpret a DSN against cwd.
    if not left or not PureWindowsPath(left).is_absolute() or not PureWindowsPath(right).is_absolute():
        return False
    return ntpath.normcase(ntpath.normpath(left)) == ntpath.normcase(ntpath.normpath(str(right)))


def readonly_uri(path: Path) -> str:
    windows = PureWindowsPath(path)
    if not windows.is_absolute():
        raise SetupError("Verification requires an absolute database path.")
    value = windows.as_posix()
    # Empty URI authority also supports UNC without SQLITE_ALLOW_URI_AUTHORITY.
    prefix = "file://" if value.startswith("//") else "file:///"
    return prefix + quote(value, safe="/:") + "?mode=ro&immutable=1"


def check_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(path) + suffix)
        try:
            sidecar.lstat()  # includes empty files, directories and dangling links
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise SetupError(f"Cannot inspect SQLite sidecar: {sidecar}. Check permissions.") from exc
        raise SetupError(f"SQLite journal sidecar present: {sidecar}. Close database consumers and let "
                         "SQLite finish normal recovery/cleanup; do not delete journals.")


def _open_guard(path: Path) -> BinaryIO:
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    # GENERIC_READ, FILE_SHARE_READ only, OPEN_EXISTING: cannot create a file.
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    try:
        return os.fdopen(fd, "rb")  # owns the Windows handle from here onward
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def snapshot(path: Path) -> Iterator[None]:
    if ";" in str(path):
        raise SetupError("The SQLite3 ODBC setup interface truncates paths at a semicolon. "
                         "Move this checkout to a path without ';'. No DSN changed.")
    try:
        info = path.stat()
    except FileNotFoundError as exc:
        raise SetupError(f"SQLite snapshot not found: {path}. Restore or generate it first; setup never creates a database.") from exc
    except OSError as exc:
        raise SetupError(f"Cannot inspect SQLite snapshot: {path}. Check file permissions.") from exc
    if not stat.S_ISREG(info.st_mode):
        raise SetupError(f"SQLite snapshot is not a regular file: {path}")
    try:
        guard = _open_guard(path)
    except OSError as exc:
        raise SetupError(f"SQLite snapshot is unreadable or in use: {path}. "
                         "Check permissions and close Altium and other database consumers.") from exc
    with guard:
        check_sidecars(path)
        try:
            header = guard.read(100)
            size = os.fstat(guard.fileno()).st_size
        except OSError as exc:
            raise SetupError(f"Cannot read SQLite snapshot: {path}.") from exc
        if len(header) != 100 or header[:16] != b"SQLite format 3\0":
            raise SetupError(f"Invalid SQLite header: {path}.")
        page = int.from_bytes(header[16:18], "big")
        page = 65536 if page == 1 else page
        if page < 512 or page > 65536 or page & (page - 1) or size < page or size % page:
            raise SetupError(f"Invalid or truncated SQLite snapshot (page size/file length): {path}.")
        yield
