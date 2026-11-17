"""Small Unicode ODBC adapter. Runtime verification executes two fixed reads."""

from contextlib import contextmanager
import ctypes as c
from pathlib import Path
from typing import Iterator

from .database import equivalent_path, readonly_uri
from .errors import SetupError

SQL_SUCCESS, SQL_SUCCESS_WITH_INFO, SQL_NO_DATA = 0, 1, 100


def _api():
    api = c.WinDLL("odbc32")
    signatures = {
        "SQLAllocHandle": [c.c_short, c.c_void_p, c.POINTER(c.c_void_p)],
        "SQLFreeHandle": [c.c_short, c.c_void_p],
        "SQLSetEnvAttr": [c.c_void_p, c.c_int, c.c_void_p, c.c_int],
        "SQLSetConnectAttrW": [c.c_void_p, c.c_int, c.c_void_p, c.c_int],
        "SQLDriverConnectW": [c.c_void_p, c.c_void_p, c.c_wchar_p, c.c_short,
                              c.c_wchar_p, c.c_short, c.POINTER(c.c_short), c.c_ushort],
        "SQLDisconnect": [c.c_void_p],
        "SQLExecDirectW": [c.c_void_p, c.c_wchar_p, c.c_int],
        "SQLFetch": [c.c_void_p],
        "SQLGetData": [c.c_void_p, c.c_ushort, c.c_short, c.c_void_p,
                       c.c_ssize_t, c.POINTER(c.c_ssize_t)],
        "SQLGetDiagRecW": [c.c_short, c.c_void_p, c.c_short, c.c_wchar_p,
                           c.POINTER(c.c_int), c.c_wchar_p, c.c_short, c.POINTER(c.c_short)],
    }
    for name, args in signatures.items():
        fn = getattr(api, name)
        fn.argtypes, fn.restype = args, c.c_short
    return api


def _check(api, result: int, kind: int, handle, operation: str) -> None:
    if result in (SQL_SUCCESS, SQL_SUCCESS_WITH_INFO):
        return
    state, native, size = c.create_unicode_buffer(6), c.c_int(), c.c_short()
    # Do not retrieve/log driver text or a connection string: existing DSNs may
    # contain private settings. SQLSTATE alone is useful and safe diagnostics.
    api.SQLGetDiagRecW(kind, handle, 1, state, c.byref(native), None, 0, c.byref(size))
    raise SetupError(f"Read-only ODBC connection failure during {operation} (SQLSTATE {state.value or 'unknown'}).")


def connection_string(name: str, path: Path) -> str:
    # Internal names are constrained too: never accept connection-string syntax.
    if not name or len(name) > 32 or not all(ch.isascii() and (ch.isalnum() or ch in "-_") for ch in name):
        raise SetupError("Invalid internal DSN name.")
    return f"DSN={name};Database={readonly_uri(path)};NoCreat=1;Timeout=5000;"


class Connection:
    def __init__(self, api, handle):
        self.api, self.handle = api, handle

    def query(self, sql: str, columns: int) -> list[tuple[str | None, ...]]:
        statement = c.c_void_p()
        _check(self.api, self.api.SQLAllocHandle(3, self.handle, c.byref(statement)),
               2, self.handle, "statement allocation")
        try:
            _check(self.api, self.api.SQLExecDirectW(statement, sql, -3), 3, statement, "query")
            rows = []
            while columns:
                result = self.api.SQLFetch(statement)
                if result == SQL_NO_DATA:
                    break
                _check(self.api, result, 3, statement, "fetch")
                row = []
                for column in range(1, columns + 1):
                    value, length = c.create_unicode_buffer(32768), c.c_ssize_t()
                    result = self.api.SQLGetData(statement, column, -8, value, c.sizeof(value), c.byref(length))
                    _check(self.api, result, 3, statement, "column read")
                    if result == SQL_SUCCESS_WITH_INFO or length.value >= c.sizeof(value):
                        raise SetupError("ODBC returned truncated verification data.")
                    row.append(None if length.value == -1 else value.value)
                rows.append(tuple(row))
            return rows
        finally:
            self.api.SQLFreeHandle(3, statement)


@contextmanager
def connect_readonly(name: str, path: Path) -> Iterator[Connection]:
    text = connection_string(name, path)
    api = _api()
    env, dbc = c.c_void_p(), c.c_void_p()
    connected = False
    try:
        _check(api, api.SQLAllocHandle(1, None, c.byref(env)), 1, env, "environment allocation")
        _check(api, api.SQLSetEnvAttr(env, 200, c.c_void_p(3), 0), 1, env, "ODBC version selection")
        _check(api, api.SQLAllocHandle(2, env, c.byref(dbc)), 1, env, "connection allocation")
        _check(api, api.SQLSetConnectAttrW(dbc, 103, c.c_void_p(5), 0), 2, dbc, "login timeout")
        _check(api, api.SQLSetConnectAttrW(dbc, 104, None, 0), 2, dbc, "disable connection tracing")
        # SQL_DRIVER_NOPROMPT, no output connection string and no GUI handle.
        _check(api, api.SQLDriverConnectW(dbc, None, text, -3, None, 0, None, 0), 2, dbc, "connect")
        connected = True
        yield Connection(api, dbc)
    finally:
        if dbc.value:
            if connected:
                api.SQLDisconnect(dbc)
            api.SQLFreeHandle(2, dbc)
        if env.value:
            api.SQLFreeHandle(1, env)


def verify_connection(name: str, path: Path) -> None:
    # Caller must hold snapshot() and have read back the DSN's plain path.
    with connect_readonly(name, path) as connection:
        connection.query("SELECT name FROM sqlite_master LIMIT 1", 1)
        rows = connection.query("PRAGMA database_list", 3)
        main = [row[2] for row in rows if row[1] == "main"]
        if len(main) != 1 or not equivalent_path(main[0], path):
            raise SetupError(f"ODBC opened a different database for '{name}'.")
