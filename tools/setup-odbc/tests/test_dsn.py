from contextlib import nullcontext
from copy import deepcopy
import ctypes
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from setup_odbc import dsn
from setup_odbc.errors import SetupError


@pytest.fixture
def backend(monkeypatch, driver):
    state = SimpleNamespace(record=None, calls=[], reads=0, fail=None, read_hook=None, verify_hook=None)

    def read(name, selected):
        assert name == dsn.DSN_NAME and selected == driver
        state.reads += 1
        if state.read_hook:
            state.read_hook()
        return deepcopy(state.record)

    class Installer:
        def create(self, name, selected):
            state.calls.append("create")
            if state.fail == "create_before":
                raise SetupError("configuration failure")
            state.record = dsn.Dsn(driver.name, {"driver": driver.dll, "nocreat": "1"})
            if state.fail == "create_after":
                raise SetupError("configuration failure")

        def database(self, name, value):
            state.calls.append(("database", value))
            if state.fail == "rollback" and len(state.calls) > 2:
                raise SetupError("rollback failure")
            if value is None:
                state.record.attributes.pop("database", None)
            else:
                state.record.attributes["database"] = value
            if state.fail in {"set_after", "interrupt"} and len(state.calls) == 1:
                if state.fail == "interrupt":
                    raise KeyboardInterrupt
                raise SetupError("configuration failure")

        def remove(self, name, selected):
            state.calls.append("remove")
            if state.fail == "remove":
                raise SetupError("remove failure")
            state.record = None

    def verify(name, path):
        state.calls.append("connect")
        if state.verify_hook:
            state.verify_hook()
        if state.fail in {"connect", "rollback", "remove"}:
            raise SetupError("connection failure")

    monkeypatch.setattr(dsn, "read_dsn", read)
    monkeypatch.setattr(dsn, "Installer", Installer)
    monkeypatch.setattr(dsn, "setup_lock", lambda name: nullcontext())
    monkeypatch.setattr(dsn, "verify_connection", verify)
    return state


def existing(driver, path=r"D:\old\components.sqlite"):
    return dsn.Dsn(driver.name, {"driver": driver.dll, "database": str(path), "description": "retained", "nocreat": "0"})


def test_new_creation_readback_and_repeat(backend, driver, snapshot_path):
    assert dsn.configure(dsn.DSN_NAME, driver, snapshot_path) == "New User DSN created."
    assert backend.calls == ["create", ("database", str(snapshot_path)), "connect"]
    assert backend.record.attributes == {"driver": driver.dll, "database": str(snapshot_path), "nocreat": "1"}
    before = deepcopy(backend.record)
    backend.calls.clear()
    assert dsn.configure(dsn.DSN_NAME, driver, snapshot_path) == "Already configured. No changes required."
    assert backend.calls == ["connect"] and backend.record == before


@pytest.mark.parametrize("check", [False, True])
@pytest.mark.parametrize("equivalent", [False, True])
def test_existing_correct_dsn_unchanged(backend, driver, snapshot_path, check, equivalent):
    value = str(snapshot_path)
    if equivalent:
        value = value.upper().replace("\\", "/").replace("/COMPONENTS.SQLITE", "/./COMPONENTS.SQLITE")
    backend.record = existing(driver, value)
    previous = deepcopy(backend.record)
    dsn.configure(dsn.DSN_NAME, driver, snapshot_path, check_only=check)
    assert backend.calls == ["connect"] and backend.record == previous


def test_move_updates_only_database(backend, driver, snapshot_path):
    backend.record = existing(driver)
    original = deepcopy(backend.record.attributes)
    assert dsn.configure(dsn.DSN_NAME, driver, snapshot_path) == "Existing DSN updated."
    assert backend.record.attributes == {**original, "database": str(snapshot_path)}
    assert backend.calls == [("database", str(snapshot_path)), "connect"]


@pytest.mark.parametrize("has_previous", [True, False])
def test_check_only_never_changes_missing_or_moved_dsn(backend, driver, snapshot_path, has_previous):
    backend.record = existing(driver) if has_previous else None
    previous = deepcopy(backend.record)
    with pytest.raises(SetupError, match="without --check-only"):
        dsn.configure(dsn.DSN_NAME, driver, snapshot_path, check_only=True)
    assert backend.record == previous and not backend.calls


@pytest.mark.parametrize("failure", ["connect", "set_after", "interrupt", "readback"])
@pytest.mark.parametrize("missing_database", [False, True])
def test_update_failures_restore_previous_attribute(backend, driver, snapshot_path, failure, missing_database):
    backend.record = existing(driver)
    if missing_database:
        del backend.record.attributes["database"]
    previous = deepcopy(backend.record)
    backend.fail = failure
    if failure == "readback":
        def fail_once():
            if backend.reads == 3:
                raise SetupError("readback failure")
        backend.read_hook = fail_once
    with pytest.raises(SetupError, match="Previous DSN database setting restored"):
        dsn.configure(dsn.DSN_NAME, driver, snapshot_path)
    assert backend.record == previous
    assert backend.calls[-1] == ("database", previous.attributes.get("database"))


@pytest.mark.parametrize("failure", ["connect", "create_before", "create_after"])
def test_failed_create_removes_only_new_dsn(backend, driver, snapshot_path, failure):
    backend.fail = failure
    with pytest.raises(SetupError, match="Newly created DSN removed"):
        dsn.configure(dsn.DSN_NAME, driver, snapshot_path)
    assert backend.record is None
    assert ("remove" in backend.calls) == (failure != "create_before")


@pytest.mark.parametrize("previous", [True, False])
def test_rollback_failure_retains_original_error(backend, driver, snapshot_path, previous):
    backend.record = existing(driver) if previous else None
    backend.fail = "rollback" if previous else "remove"
    with pytest.raises(SetupError, match="connection failure.*Rollback incomplete"):
        dsn.configure(dsn.DSN_NAME, driver, snapshot_path)


def test_check_only_failed_connection_does_not_mutate(backend, driver, snapshot_path):
    backend.record = existing(driver, snapshot_path)
    previous = deepcopy(backend.record)
    backend.fail = "connect"
    with pytest.raises(SetupError, match="connection failure"):
        dsn.configure(dsn.DSN_NAME, driver, snapshot_path, check_only=True)
    assert backend.calls == ["connect"] and backend.record == previous


@pytest.mark.parametrize("previous", [True, False])
@pytest.mark.parametrize("what", ["database", "description"])
def test_rollback_never_overwrites_concurrent_changes(backend, driver, snapshot_path, previous, what):
    backend.record = existing(driver) if previous else None
    backend.fail = "connect"
    backend.verify_hook = lambda: backend.record.attributes.update({what: "concurrent edit"})
    with pytest.raises(SetupError, match="Rollback incomplete"):
        dsn.configure(dsn.DSN_NAME, driver, snapshot_path)
    assert backend.record.attributes[what] == "concurrent edit"
    assert backend.calls[-1] == "connect"


def test_concurrent_change_before_mutation_stops_setup(backend, driver, snapshot_path):
    def change():
        if backend.reads == 2:
            backend.record = existing(driver)
    backend.read_hook = change
    with pytest.raises(SetupError, match="changed concurrently before"):
        dsn.configure(dsn.DSN_NAME, driver, snapshot_path)
    assert not backend.calls


def test_inspection_permission_failure_never_mutates(backend, driver, snapshot_path):
    def fail():
        raise SetupError("permissions failure")
    backend.read_hook = fail
    with pytest.raises(SetupError, match="permissions"):
        dsn.configure(dsn.DSN_NAME, driver, snapshot_path)
    assert not backend.calls


@pytest.fixture
def registrations(monkeypatch):
    records = {}

    def values(scope, path, bits):
        record = records.get((scope, bits))
        if path.endswith("ODBC Data Sources"):
            return {dsn.DSN_NAME.casefold(): record.driver} if record and record.driver else {}
        return record.attributes if record else None
    monkeypatch.setattr(dsn, "registry_values", values)
    return records


def test_shared_user_registry_views(registrations, driver):
    record = existing(driver)
    registrations["User", 64] = registrations["User", 32] = record
    assert dsn.read_dsn(dsn.DSN_NAME, driver) == record


@pytest.mark.parametrize("kind", ["system", "user_and_system", "32_only", "other_driver", "wrong_dll", "missing_key", "missing_list", "different_views"])
def test_registry_conflicts(registrations, driver, kind):
    record = existing(driver)
    registrations["User", 64] = record
    if kind == "system":
        registrations.clear()
        registrations["System", 32] = record
    elif kind == "user_and_system":
        registrations["System", 64] = record
    elif kind == "32_only":
        registrations["User", 32] = registrations.pop(("User", 64))
    elif kind == "other_driver":
        registrations["User", 64] = dsn.Dsn("Other driver", record.attributes)
    elif kind == "wrong_dll":
        record.attributes["driver"] = r"C:\Windows\SysWOW64\sqlite3odbc.dll"
    elif kind == "missing_key":
        registrations["User", 64] = dsn.Dsn(driver.name, None)
    elif kind == "missing_list":
        registrations["User", 64] = dsn.Dsn(None, record.attributes)
    else:
        registrations["User", 32] = existing(driver, r"Z:\other.sqlite")
    with pytest.raises(SetupError, match="Conflicting DSN"):
        dsn.read_dsn(dsn.DSN_NAME, driver)


@pytest.mark.parametrize("attribute", dsn.UNSAFE_OPTIONS)
def test_unsafe_connection_options(registrations, driver, attribute):
    record = existing(driver)
    record.attributes[attribute] = "unsafe"
    registrations["User", 64] = record
    with pytest.raises(SetupError, match=attribute):
        dsn.read_dsn(dsn.DSN_NAME, driver)


def test_native_installer_signatures_and_unicode_attribute_buffers(monkeypatch, driver):
    api = SimpleNamespace(**{key: Mock(return_value=1) for key in (
        "SQLConfigDataSourceW", "SQLWritePrivateProfileStringW", "SQLGetConfigMode", "SQLSetConfigMode")})
    def mode(pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_ushort))[0] = 2
        return 1
    api.SQLGetConfigMode.side_effect = mode
    monkeypatch.setattr(ctypes, "WinDLL", lambda name: api, raising=False)
    installer = dsn.Installer()
    installer.create(dsn.DSN_NAME, driver)
    args = api.SQLConfigDataSourceW.call_args.args
    assert args[:3] == (None, 1, driver.name)
    assert "DSN=AltiumComponents\0NoCreat=1\0\0" == args[3][:].rstrip("\0") + "\0\0"
    installer.database(dsn.DSN_NAME, "D:\\Україна space\\parts.sqlite")
    api.SQLWritePrivateProfileStringW.assert_called_once_with(dsn.DSN_NAME, "Database", "D:\\Україна space\\parts.sqlite", "ODBC.INI")
    assert [call.args for call in api.SQLSetConfigMode.call_args_list] == [(1,), (2,)]
    installer.database(dsn.DSN_NAME, None)
    assert api.SQLWritePrivateProfileStringW.call_args.args[2] is None
    installer.remove(dsn.DSN_NAME, driver)
    assert api.SQLConfigDataSourceW.call_args.args[1] == 3


def test_native_profile_failure_restores_installer_scope(monkeypatch):
    api = SimpleNamespace(**{key: Mock(return_value=1) for key in (
        "SQLConfigDataSourceW", "SQLWritePrivateProfileStringW", "SQLGetConfigMode", "SQLSetConfigMode")})
    api.SQLWritePrivateProfileStringW.return_value = 0
    monkeypatch.setattr(ctypes, "WinDLL", lambda name: api, raising=False)
    with pytest.raises(SetupError, match="configuration failed"):
        dsn.Installer().database(dsn.DSN_NAME, "D:\\test.sqlite")
    assert api.SQLSetConfigMode.call_args.args == (0,)
