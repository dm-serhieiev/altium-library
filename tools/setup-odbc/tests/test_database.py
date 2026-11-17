import os
from pathlib import Path, PureWindowsPath
import sys

import pytest

from setup_odbc import database
from setup_odbc.errors import SetupError


def test_path_discovery_does_not_use_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    expected = Path(database.__file__).resolve().parents[4] / "database/components.sqlite"
    assert database.database_path() == expected
    exe = tmp_path / "Moved library Україна" / "tools/setup-odbc.exe"
    monkeypatch.setattr(database.sys, "frozen", True, raising=False)
    monkeypatch.setattr(database.sys, "executable", str(exe))
    assert database.database_path() == exe.parent.parent / "database/components.sqlite"


@pytest.mark.parametrize("left,right,expected", [
    (r"C:\Library\components.sqlite", "c:/library/./COMPONENTS.sqlite", True),
    (r"D:\Library\components.sqlite", r"C:\Library\components.sqlite", False),
    ("components.sqlite", "components.sqlite", False),
    (r"\components.sqlite", r"C:\components.sqlite", False),
    (r"\\server\share\a.sqlite", "//SERVER/share/a.sqlite", True),
    (None, r"C:\a.sqlite", False),
])
def test_absolute_path_comparison(left, right, expected):
    assert database.equivalent_path(left, right) == expected


def test_uri_escaping_and_unc():
    assert database.readonly_uri(PureWindowsPath(r"D:\space Україна\x%#?.sqlite")) == (
        "file:///D:/space%20%D0%A3%D0%BA%D1%80%D0%B0%D1%97%D0%BD%D0%B0/x%25%23%3F.sqlite?mode=ro&immutable=1")
    assert database.readonly_uri(PureWindowsPath(r"\\host\share\x.sqlite")) == "file:////host/share/x.sqlite?mode=ro&immutable=1"


@pytest.mark.parametrize("kind", ["missing", "directory", "empty", "header", "truncated", "pagesize", "semicolon"])
def test_invalid_snapshot(snapshot_path, kind):
    path = snapshot_path
    if kind in {"missing", "directory"}:
        path.unlink()
        if kind == "directory":
            path.mkdir()
    elif kind == "empty":
        path.write_bytes(b"")
    elif kind == "header":
        path.write_bytes(b"x" * 4096)
    elif kind == "truncated":
        path.write_bytes(path.read_bytes()[:-1])
    elif kind == "pagesize":
        data = bytearray(path.read_bytes())
        data[16:18] = b"\x00\x07"
        path.write_bytes(data)
    else:
        path = path.with_name("semi;colon.sqlite")
    with pytest.raises(SetupError), database.snapshot(path):
        pytest.fail("Invalid snapshot accepted")


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
@pytest.mark.parametrize("kind", ["empty", "directory", "dangling"])
def test_sidecar_entries_are_preserved(snapshot_path, suffix, kind):
    sidecar = Path(str(snapshot_path) + suffix)
    if kind == "empty":
        sidecar.write_bytes(b"")
    elif kind == "directory":
        sidecar.mkdir()
    else:
        try:
            sidecar.symlink_to(sidecar.with_name("missing"))
        except OSError:
            pytest.skip("Windows symlink creation requires Developer Mode or privilege")
    before = snapshot_path.read_bytes()
    with pytest.raises(SetupError, match="sidecar present"), database.snapshot(snapshot_path):
        pytest.fail("Sidecar accepted")
    sidecar.lstat()
    assert snapshot_path.read_bytes() == before


def test_sidecar_inspection_failure_is_not_absence(snapshot_path, monkeypatch):
    original = Path.lstat

    def fail(path, *args, **kwargs):
        if str(path).endswith("-wal"):
            raise PermissionError("synthetic")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "lstat", fail)
    with pytest.raises(SetupError, match="Cannot inspect"), database.snapshot(snapshot_path):
        pytest.fail("Inspection failure accepted")


def test_real_guard_prevents_writes_and_replacement(snapshot_path):
    if sys.platform != "win32":
        pytest.skip("Windows sharing modes")
    before = snapshot_path.read_bytes()
    candidate = snapshot_path.with_name("candidate.sqlite")
    candidate.write_bytes(before)
    with database.snapshot(snapshot_path):
        with pytest.raises(PermissionError):
            snapshot_path.open("r+b")
        with pytest.raises(PermissionError):
            os.replace(candidate, snapshot_path)
        assert snapshot_path.read_bytes() == before
    # Handles closed, even after validation exceptions (other tests remove files).
    os.replace(candidate, snapshot_path)
    assert snapshot_path.read_bytes() == before


def test_open_error_has_context(snapshot_path, monkeypatch):
    def fail(path):
        raise PermissionError("synthetic")
    monkeypatch.setattr(database, "_open_guard", fail)
    with pytest.raises(SetupError, match="unreadable or in use"), database.snapshot(snapshot_path):
        pytest.fail("Open failure accepted")
