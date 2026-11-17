from types import SimpleNamespace
from unittest.mock import Mock
import sys

import pytest

from setup_odbc import drivers
from setup_odbc.errors import SetupError


@pytest.mark.parametrize("installed", [[], [drivers.Driver(drivers.DEFAULT_DRIVER, 32, "sqlite3odbc.dll")],
                                         [drivers.Driver("Other SQLite Driver", 64, "sqlite3odbc.dll")]])
def test_missing_exact_64bit_driver(installed):
    with pytest.raises(SetupError, match="Required 64-bit driver.*sqliteodbc_w64.exe"):
        drivers.select_driver(drivers.DEFAULT_DRIVER, installed)


@pytest.mark.parametrize("dll", [r"C:\other.dll", "sqlite3odbc.dll", "", r"\System32\sqlite3odbc.dll"])
def test_incompatible_implementation(dll):
    with pytest.raises(SetupError, match="not the supported"):
        drivers.select_driver(drivers.DEFAULT_DRIVER, [drivers.Driver(drivers.DEFAULT_DRIVER, 64, dll)])


@pytest.mark.parametrize("name", ["", "SQL Server", "SQLite*", "SQLite?", "SQLite;Other", "SQLite\0Driver"])
def test_alias_must_be_exact(name, driver):
    with pytest.raises(SetupError, match="exact installed name"):
        drivers.select_driver(name, [driver])


def test_explicit_compatible_alias(driver):
    alias = drivers.Driver("Renamed SQLite3 ODBC Driver", 64, driver.dll)
    assert drivers.select_driver(alias.name, [driver, alias]) == alias


@pytest.mark.parametrize("platform,size", [("linux", 8), ("win32", 4)])
def test_unsupported_host(monkeypatch, platform, size):
    monkeypatch.setattr(drivers, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(drivers.ctypes, "sizeof", lambda value: size)
    with pytest.raises(SetupError, match="64-bit Windows is required"):
        drivers.require_windows_x64()


def test_inspect_both_views_only_sqlite_names(monkeypatch):
    calls = []
    def read(hive, path, bits, **kwargs):
        calls.append((hive, path, bits))
        if path.endswith("ODBC Drivers"):
            return {"sqlite3 odbc driver": "Installed", "unrelated": "Installed"}
        assert "sqlite" in path.casefold()
        return {"driver": rf"C:\Windows\{'System32' if bits == 64 else 'SysWOW64'}\sqlite3odbc.dll"}
    monkeypatch.setattr(drivers, "registry_values", read)
    result = drivers.installed_drivers()
    assert [(d.name, d.bits) for d in result] == [(drivers.DEFAULT_DRIVER, 64), (drivers.DEFAULT_DRIVER, 32)]
    assert {call[2] for call in calls} == {32, 64}


@pytest.mark.parametrize("failure", [PermissionError, OSError])
def test_registry_errors_not_absence(monkeypatch, failure):
    fake = SimpleNamespace(HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2, KEY_READ=4,
                           KEY_WOW64_64KEY=8, KEY_WOW64_32KEY=16,
                           OpenKey=Mock(side_effect=failure("synthetic")))
    monkeypatch.setitem(sys.modules, "winreg", fake)
    with pytest.raises(SetupError, match="read permissions"):
        drivers.registry_values("User", "test", 64)


def test_registry_missing_key_is_absent(monkeypatch):
    fake = SimpleNamespace(HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2, KEY_READ=4,
                           KEY_WOW64_64KEY=8, KEY_WOW64_32KEY=16,
                           OpenKey=Mock(side_effect=FileNotFoundError))
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert drivers.registry_values("User", "test", 32) is None
    fake.OpenKey.assert_called_once_with(1, "test", 0, 20)


def test_driver_numeric_metadata_and_case_insensitive_settings(monkeypatch):
    from contextlib import nullcontext
    values = [("Driver", r"C:\Windows\System32\sqlite3odbc.dll", 1), ("UsageCount", 1, 4)]
    fake = SimpleNamespace(HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2, KEY_READ=4,
                           KEY_WOW64_64KEY=8, KEY_WOW64_32KEY=16, REG_SZ=1, REG_EXPAND_SZ=2,
                           OpenKey=lambda *args: nullcontext(object()), QueryInfoKey=lambda key: (0, 2, 0),
                           EnumValue=lambda key, i: values[i])
    monkeypatch.setitem(sys.modules, "winreg", fake)
    assert drivers.registry_values("System", "driver", 64, text_only=False) == {"driver": values[0][1]}
    with pytest.raises(SetupError, match="non-text"):
        drivers.registry_values("User", "dsn", 64)
    values[:] = [("Database", r"%TEMP%\parts.sqlite", 2), ("Driver", r"C:\sqlite3odbc.dll", 1)]
    with pytest.raises(SetupError, match="expandable"):
        drivers.registry_values("User", "dsn", 64)
