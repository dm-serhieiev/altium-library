"""Offline PowerShell tests. ODBC cmdlets are mocked, never production DSNs."""

from copy import deepcopy
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest


TOOLS = Path(__file__).resolve().parents[2]
SCRIPT = TOOLS / "setup-odbc.ps1"
DRIVER = "SQLite3 ODBC Driver"
DRIVER_INFO = {"Name": DRIVER, "Platform": "64-bit", "Attribute": {"Driver": "C:\\Windows\\System32\\sqlite3odbc.dll"}}
PORTABLE = b'ConnectionString=Provider=MSDASQL.1;Persist Security Info=False;Extended Properties="DSN=AltiumComponents;"'


def dsn(path, *, name="AltiumComponents", driver=DRIVER, platform="64-bit", scope="User", **attributes):
    return {"Name": name, "DriverName": driver, "Platform": platform, "DsnType": scope,
            "Attribute": {"Database": str(path), **attributes}}


@pytest.fixture
def setup_repo(tmp_path):
    if sys.platform != "win32":
        pytest.skip("Windows PowerShell 5.1 setup tests")
    root = tmp_path / "Library with spaces and Україна"
    (root / "tools").mkdir(parents=True)
    (root / "database").mkdir()
    shutil.copyfile(SCRIPT, root / "tools/setup-odbc.ps1")
    shutil.copyfile(TOOLS.parent / "database/Components.DbLib", root / "database/Components.DbLib")
    database = root / "database/components.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE parts (IPN TEXT)")
        connection.execute("INSERT INTO parts VALUES ('SYNTHETIC-1')")
        connection.commit()
    return root


@pytest.fixture
def run_setup(setup_repo, tmp_path):
    def run(**overrides):
        database = setup_repo / "database/components.sqlite"
        scenario = {"drivers": [DRIVER_INFO], "driverName": DRIVER,
                    "dsns": [], "expectedDatabase": str(database), **overrides}
        source = tmp_path / "scenario.json"
        source.write_text(json.dumps(scenario), encoding="utf-8")
        before = {p.relative_to(setup_repo): p.read_bytes() for p in setup_repo.rglob("*") if p.is_file()}
        result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                 str(Path(__file__).with_name("odbc_setup_harness.ps1")),
                                 str(setup_repo / "tools/setup-odbc.ps1"), str(source)],
                                cwd=tmp_path, capture_output=True, encoding="utf-8", timeout=30)
        reports = [line[7:] for line in result.stdout.splitlines() if line.startswith("RESULT:")]
        assert len(reports) == 1, result.stdout + result.stderr
        report = json.loads(reports[0])
        assert result.returncode == report["code"]
        assert {p.relative_to(setup_repo): p.read_bytes() for p in setup_repo.rglob("*") if p.is_file()} == before
        report["output"] = result.stdout
        return report
    return run


def test_create_from_unrelated_cwd_unicode_and_spaces(setup_repo, run_setup):
    report = run_setup()
    assert report["code"] == 0, report
    assert report["calls"] == ["Add", "Connect"]
    assert report["dsns"] == [dsn(setup_repo / "database/components.sqlite", NoCreat="1")]
    assert "New User DSN created" in report["output"]
    assert "connection is ready" in report["output"]


@pytest.mark.parametrize("check", [False, True])
@pytest.mark.parametrize("equivalent", [False, True])
def test_existing_correct_dsn_is_not_modified(setup_repo, run_setup, check, equivalent):
    path = str(setup_repo / "database/components.sqlite")
    if equivalent:
        path = path.upper().replace("\\", "/").replace("/COMPONENTS.SQLITE", "/./COMPONENTS.SQLITE")
    original = [dsn(path, Description="keep my settings")]
    report = run_setup(dsns=original, checkOnly=check)
    assert report["code"] == 0, report
    assert report["calls"] == ["Connect"]
    assert report["dsns"] == original
    assert "Already configured. No changes required." in report["output"]


def test_move_changes_only_selected_database(setup_repo, run_setup):
    unrelated = dsn("Z:\\other.sqlite", name="OtherApp", scope="System", driver="Other driver")
    original = [dsn("D:\\previous\\components.sqlite", Description="retained", NoCreat="0"), unrelated]
    report = run_setup(dsns=original)
    assert report["code"] == 0, report
    expected = deepcopy(original)
    expected[0]["Attribute"]["Database"] = str(setup_repo / "database/components.sqlite")
    assert report["dsns"] == expected
    assert report["calls"] == ["Set", "Connect"]


@pytest.mark.parametrize("kind", ["missing", "directory", "empty", "bad_header", "truncated", "journal"])
def test_invalid_snapshot_prevents_changes(setup_repo, run_setup, kind):
    database = setup_repo / "database/components.sqlite"
    if kind in {"missing", "directory"}:
        database.unlink()
        if kind == "directory":
            database.mkdir()
    elif kind == "empty":
        database.write_bytes(b"")
    elif kind == "bad_header":
        database.write_bytes(b"x" * 4096)
    elif kind == "truncated":
        database.write_bytes(database.read_bytes()[:-1])
    else:
        database.with_name(database.name + "-wal").write_bytes(b"")
    report = run_setup()
    assert report["code"] != 0 and not report["calls"], report
    assert "ready" not in report["output"]


@pytest.mark.parametrize("drivers", [[], [{"Name": DRIVER, "Platform": "32-bit"}], [{"Name": "Other SQLite Driver", "Platform": "64-bit"}]])
def test_missing_exact_64bit_driver(run_setup, drivers):
    report = run_setup(drivers=drivers)
    assert report["code"] == 1 and not report["calls"]
    assert "Required 64-bit driver" in report["error"]
    assert "sqliteodbc_w64.exe" in report["error"]


@pytest.mark.parametrize("option", [{"driverError": True}, {"dsnError": True}])
def test_permission_errors_are_not_absence(run_setup, option):
    report = run_setup(**option)
    assert report["code"] == 1 and not report["calls"]
    assert "permissions" in report["error"]


@pytest.mark.parametrize("conflict", [{"driver": "Other driver"}, {"scope": "System"}, {"platform": "32-bit"}])
def test_conflicting_dsn_never_overwritten(setup_repo, run_setup, conflict):
    original = [dsn(setup_repo / "database/components.sqlite", **conflict)]
    report = run_setup(dsns=original)
    assert report["code"] == 1 and "Conflicting DSN" in report["error"]
    assert not report["calls"] and report["dsns"] == original


def test_same_name_system_and_user_is_conflict(setup_repo, run_setup):
    original = [dsn(setup_repo / "database/components.sqlite"), dsn("Z:\\other.sqlite", scope="System")]
    report = run_setup(dsns=original)
    assert report["code"] == 1 and not report["calls"]
    assert report["dsns"] == original


def test_shared_user_dsn_views_are_not_a_false_conflict(setup_repo, run_setup):
    path = setup_repo / "database/components.sqlite"
    original = [dsn(path), dsn(path, platform="32-bit")]
    report = run_setup(dsns=original)
    assert report["code"] == 0, report
    assert report["calls"] == ["Connect"] and report["dsns"] == original


@pytest.mark.parametrize("attribute", ["TraceFile", "LoadExt", "AttachAs", "JournalMode", "SyncPragma"])
def test_connection_side_effect_options_rejected(setup_repo, run_setup, attribute):
    report = run_setup(dsns=[dsn(setup_repo / "database/components.sqlite", **{attribute: "unsafe"})])
    assert report["code"] == 1 and not report["calls"]
    assert attribute in report["error"]


@pytest.mark.parametrize("existing", [False, True])
def test_checkonly_missing_or_moved_makes_no_changes(run_setup, existing):
    original = [dsn("D:\\previous\\components.sqlite")] if existing else []
    report = run_setup(dsns=original, checkOnly=True)
    assert report["code"] == 1 and not report["calls"]
    assert "without -CheckOnly" in report["error"] and report["dsns"] == original


@pytest.mark.parametrize("failure", ["connectionFailure", "setFailure", "readbackError"])
def test_update_failure_restores_previous_settings(run_setup, failure):
    original = [dsn("D:\\previous\\components.sqlite", Description="retained", NoCreat="1")]
    report = run_setup(dsns=original, **{failure: True})
    assert report["code"] == 1 and report["dsns"] == original
    assert report["calls"].count("Set") == 2
    assert "restored" in report["error"] and "ready" not in report["output"]


def test_missing_previous_database_attribute_restored(run_setup):
    original = dsn("unused", Description="retained")
    del original["Attribute"]["Database"]
    report = run_setup(dsns=[original], connectionFailure=True)
    assert report["code"] == 1 and report["dsns"] == [original]


def test_create_connection_failure_removes_only_new_dsn(run_setup):
    original = [dsn("Z:\\unrelated.sqlite", name="OtherApp")]
    report = run_setup(dsns=original, connectionFailure=True)
    assert report["code"] == 1 and report["dsns"] == original
    assert report["calls"] == ["Add", "Connect", "Remove"]


@pytest.mark.parametrize("failure", ["before", "after"])
def test_creation_error_cleanup(run_setup, failure):
    report = run_setup(addFailure=failure)
    assert report["code"] == 1 and report["dsns"] == []


@pytest.mark.parametrize("existing", [False, True])
def test_incomplete_rollback_reported(run_setup, existing):
    report = run_setup(dsns=[dsn("D:\\previous\\components.sqlite")] if existing else [],
                       connectionFailure=True, rollbackFailure=existing, removeFailure=not existing)
    assert report["code"] == 1 and "Rollback incomplete" in report["error"]


def test_checkonly_connection_failure_never_mutates(setup_repo, run_setup):
    original = [dsn(setup_repo / "database/components.sqlite")]
    report = run_setup(dsns=original, checkOnly=True, connectionFailure=True)
    assert report["code"] == 1 and report["dsns"] == original
    assert report["calls"] == ["Connect"]


def test_explicit_driver_name_is_validated(run_setup):
    selected = "Renamed SQLite3 ODBC Driver"
    report = run_setup(driverName=selected, drivers=[{**DRIVER_INFO, "Name": selected}])
    assert report["code"] == 0 and report["dsns"][0]["DriverName"] == selected
    rejected = run_setup(driverName="SQLite*")
    assert rejected["code"] == 1 and not rejected["calls"]


def test_other_sqlite_implementation_is_not_substituted(run_setup):
    report = run_setup(drivers=[{**DRIVER_INFO, "Attribute": {"Driver": "C:\\other-sqlite.dll"}}])
    assert report["code"] == 1 and not report["calls"]
    assert "not the supported SQLite3" in report["error"]


def test_semicolon_in_path_fails_before_dsn_changes(setup_repo, tmp_path):
    moved = tmp_path / "Library;semicolon"
    shutil.copytree(setup_repo, moved)
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                             str(moved / "tools/setup-odbc.ps1"), "-CheckOnly"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and "truncates paths at a semicolon" in result.stderr


def test_dblib_portable_connection_and_crlf_preserved():
    data = (TOOLS.parent / "database/Components.DbLib").read_bytes()
    lines = data.splitlines()
    assert [line for line in lines if line.startswith(b"ConnectionString=")] == [PORTABLE]
    assert data.count(b"\n") == data.count(b"\r\n")
    assert b"Database=" not in data and b"Driver=" not in data


def test_public_cli_missing_snapshot_exit_code(setup_repo, tmp_path):
    (setup_repo / "database/components.sqlite").unlink()
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                             str(setup_repo / "tools/setup-odbc.ps1"), "-CheckOnly"], cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert "snapshot not found" in result.stderr


def test_public_cli_32bit_host_is_rejected(setup_repo, tmp_path):
    shell = Path(os.environ["WINDIR"]) / "SysWOW64/WindowsPowerShell/v1.0/powershell.exe"
    if not shell.is_file():
        pytest.skip("No 32-bit Windows PowerShell installed")
    result = subprocess.run([str(shell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                             str(setup_repo / "tools/setup-odbc.ps1"), "-CheckOnly"], cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and "64-bit Windows PowerShell is required" in result.stderr


def test_optional_real_sqlite_odbc_driver(setup_repo, tmp_path, request):
    if not request.config.getoption("--odbc-integration"):
        pytest.skip("Optional installed-driver test: use --odbc-integration")
    moved = tmp_path / "Moved library Україна with spaces percent%"
    shutil.copytree(setup_repo, moved)
    invalid = tmp_path / "Corrupt snapshot repository"
    shutil.copytree(setup_repo, invalid)
    corrupt = invalid / "database/components.sqlite"
    data = bytearray(corrupt.read_bytes())
    data[100] = 255  # Invalid b-tree page type; header validation still succeeds.
    corrupt.write_bytes(data)
    files = [root / "database" / name for root in (setup_repo, moved, invalid)
             for name in ("components.sqlite", "Components.DbLib")]
    before = {p: p.read_bytes() for p in files}
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                             str(Path(__file__).with_name("odbc_setup_integration.ps1")), str(SCRIPT),
                             str(setup_repo / "tools"), str(moved / "tools"), str(invalid / "tools")],
                            cwd=tmp_path, capture_output=True, encoding="utf-8", timeout=60)
    if result.returncode == 77:
        pytest.skip("SQLite3 64-bit ODBC driver not installed")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "INTEGRATION:" in result.stdout
    assert {p: p.read_bytes() for p in files} == before
    for root in (setup_repo, moved, invalid):
        assert {p.name for p in (root / "database").iterdir()} == {"components.sqlite", "Components.DbLib"}
