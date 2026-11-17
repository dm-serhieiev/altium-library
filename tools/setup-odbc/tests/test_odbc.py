import ctypes as c
from pathlib import PureWindowsPath
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from setup_odbc import odbc
from setup_odbc.errors import SetupError


def test_connection_string_uri_readonly_no_create():
    text = odbc.connection_string("Test-123", PureWindowsPath(r"C:\Space % Україна\parts.sqlite"))
    assert "DSN=Test-123;Database=file:///C:/Space%20%25%20" in text
    assert text.endswith("?mode=ro&immutable=1;NoCreat=1;Timeout=5000;")
    assert "ReadOnly=" not in text


@pytest.mark.parametrize("name", ["x;Driver=other", "x\0y", "", "x" * 33])
def test_internal_dsn_not_connection_string_injection(name):
    with pytest.raises(SetupError, match="Invalid internal"):
        odbc.connection_string(name, PureWindowsPath(r"C:\x.sqlite"))


@pytest.fixture
def api(monkeypatch):
    names = ("SQLAllocHandle", "SQLFreeHandle", "SQLSetEnvAttr", "SQLSetConnectAttrW", "SQLDriverConnectW",
             "SQLDisconnect", "SQLExecDirectW", "SQLFetch", "SQLGetData", "SQLGetDiagRecW")
    fake = SimpleNamespace(**{name: Mock(return_value=0) for name in names})
    def allocate(kind, parent, output):
        c.cast(output, c.POINTER(c.c_void_p))[0] = kind
        return 0
    fake.SQLAllocHandle.side_effect = allocate
    monkeypatch.setattr(odbc, "_api", lambda: fake)
    return fake


@pytest.mark.parametrize("failure", ["SQLSetEnvAttr", "SQLSetConnectAttrW", "SQLDriverConnectW", "SQLExecDirectW", "SQLFetch", "SQLGetData", None])
def test_native_handle_cleanup_at_every_stage(api, failure):
    api.SQLFetch.side_effect = [0, 100]
    if failure:
        getattr(api, failure).side_effect = None
        getattr(api, failure).return_value = -1
    def run():
        with odbc.connect_readonly("Test", PureWindowsPath(r"C:\x.sqlite")) as connection:
            connection.query("SELECT name FROM sqlite_master LIMIT 1", 1)
    if failure:
        with pytest.raises(SetupError, match="connection failure"):
            run()
    else:
        run()
    freed = [call.args[0] for call in api.SQLFreeHandle.call_args_list]
    assert 1 in freed
    if failure != "SQLSetEnvAttr":
        assert 2 in freed
    if failure not in {"SQLSetEnvAttr", "SQLSetConnectAttrW", "SQLDriverConnectW"}:
        assert freed == [3, 2, 1]
        api.SQLDisconnect.assert_called_once()
    else:
        api.SQLDisconnect.assert_not_called()


def test_connect_uses_unicode_no_prompt_no_output_connection_string(api):
    with odbc.connect_readonly("Test", PureWindowsPath(r"C:\x.sqlite")):
        pass
    args = api.SQLDriverConnectW.call_args.args
    assert args[1] is None and args[3:] == (-3, None, 0, None, 0)
    assert [call.args[1] for call in api.SQLSetConnectAttrW.call_args_list] == [103, 104]


def test_truncated_verification_data_rejected(api):
    api.SQLFetch.return_value = 0
    api.SQLGetData.return_value = 1
    with odbc.connect_readonly("Test", PureWindowsPath(r"C:\x.sqlite")) as connection:
        with pytest.raises(SetupError, match="truncated"):
            connection.query("PRAGMA database_list", 3)
    assert [call.args[0] for call in api.SQLFreeHandle.call_args_list] == [3, 2, 1]


@pytest.mark.parametrize("actual", [r"D:\wrong.sqlite", None])
def test_expected_database_is_checked(monkeypatch, actual):
    from contextlib import nullcontext
    query = Mock(side_effect=[[], [("0", "main", actual)]])
    monkeypatch.setattr(odbc, "connect_readonly", lambda *args: nullcontext(SimpleNamespace(query=query)))
    with pytest.raises(SetupError, match="different database"):
        odbc.verify_connection("Test", PureWindowsPath(r"C:\expected.sqlite"))
    assert [call.args[0] for call in query.call_args_list] == ["SELECT name FROM sqlite_master LIMIT 1", "PRAGMA database_list"]
