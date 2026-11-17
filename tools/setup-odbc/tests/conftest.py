from contextlib import closing
import ctypes
import sqlite3
import sys

import pytest

from setup_odbc.drivers import Driver, DEFAULT_DRIVER


def pytest_addoption(parser):
    parser.addoption("--odbc-integration", action="store_true", help="Use disposable databases and a temporary User DSN with the real driver")
    parser.addoption("--setup-executable", help="Candidate executable for Windows packaging tests")


@pytest.fixture(autouse=True)
def no_native_odbc_in_unit_tests(request, monkeypatch):
    if request.node.get_closest_marker("integration"):
        if not request.config.getoption("--odbc-integration") or sys.platform != "win32":
            pytest.skip("Opt-in Windows driver test: --odbc-integration")
        return
    if hasattr(ctypes, "WinDLL"):
        original = ctypes.WinDLL

        def guard(name, *args, **kwargs):
            if str(name).lower() in {"odbc32", "odbccp32"}:
                pytest.fail("Ordinary tests must mock ODBC APIs")
            return original(name, *args, **kwargs)
        monkeypatch.setattr(ctypes, "WinDLL", guard)


@pytest.fixture
def driver():
    return Driver(DEFAULT_DRIVER, 64, r"C:\Windows\System32\sqlite3odbc.dll")


@pytest.fixture
def snapshot_path(tmp_path):
    path = tmp_path / "Library with spaces Україна % #" / "database" / "components.sqlite"
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE parts (IPN TEXT)")
        connection.execute("INSERT INTO parts VALUES ('SYNTHETIC-1')")
        connection.commit()
    return path
