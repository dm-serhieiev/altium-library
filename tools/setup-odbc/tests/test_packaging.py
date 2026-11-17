"""Real frozen executable tests. Never configure the public DSN."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.fixture
def packaged_repo(request, tmp_path):
    executable = request.config.getoption("--setup-executable")
    if not executable or sys.platform != "win32":
        pytest.skip("Windows executable tests: --setup-executable <candidate>")
    root = tmp_path / "Repository with spaces Україна"
    tools = root / "tools"
    tools.mkdir(parents=True)
    target = tools / "setup-odbc.exe"
    shutil.copyfile(executable, target)
    return root, target


def environment():
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith("PYTHON") and key.upper() != "VIRTUAL_ENV"}
    env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    return env


@pytest.mark.parametrize("arguments,code", [(["--help"], 0), (["--force"], 2), (["--config", "x"], 2), (["--check-only"], 1), ([], 1)])
def test_standalone_cli_from_another_cwd(packaged_repo, tmp_path, arguments, code):
    root, exe = packaged_repo
    # Decoy config/database cannot influence executable-relative discovery.
    (tmp_path / "components.sqlite").write_bytes(b"decoy")
    (exe.parent / "config.toml").write_text("not valid TOML", encoding="utf-8")
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = subprocess.run([str(exe), *arguments], cwd=tmp_path, env=environment(),
                            input="", capture_output=True, encoding="utf-8", timeout=30)
    assert result.returncode == code, result.stdout + result.stderr
    assert "Press Enter" not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    if code == 1:
        assert "snapshot not found" in result.stderr
        assert str(root / "database/components.sqlite") in result.stderr
    if code == 0:
        assert "--check-only" in result.stdout and "--driver-name" in result.stdout
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_candidate_rejects_journal_without_driver_or_dsn(packaged_repo, snapshot_path, tmp_path):
    root, exe = packaged_repo
    (root / "database").mkdir()
    target = root / "database/components.sqlite"
    shutil.copyfile(snapshot_path, target)
    sidecar = target.with_name(target.name + "-wal")
    sidecar.write_bytes(b"")
    before = target.read_bytes()
    result = subprocess.run([str(exe), "--check-only"], cwd=tmp_path, env=environment(),
                            input="", capture_output=True, encoding="utf-8", timeout=30)
    assert result.returncode == 1 and "sidecar present" in result.stderr
    assert target.read_bytes() == before and sidecar.read_bytes() == b""


@pytest.mark.parametrize("mode", ["owned", "terminal", "ci"])
@pytest.mark.parametrize("argument,code", [("--help", 0), ("--invalid", 2), ("--check-only", 1)])
def test_real_console_ownership_and_exit_codes(packaged_repo, tmp_path, mode, argument, code):
    _, exe = packaged_repo
    helper = Path(__file__).with_name("windows_console_smoke.py")
    result = subprocess.run([sys.executable, str(helper), str(exe), mode, argument],
                            cwd=tmp_path, capture_output=True, encoding="utf-8",
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=50)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["returncode"] == code
    assert report["paused"] == (mode == "owned")


def test_locked_executable_preserves_previous_candidate(packaged_repo):
    import ctypes as c
    from ctypes import wintypes
    _, target = packaged_repo
    before = target.read_bytes()
    candidate = target.with_name("candidate.exe")
    candidate.write_bytes(b"candidate")
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, c.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(target), 0x80000000, 1, None, 3, 0, None)
    assert handle != c.c_void_p(-1).value
    try:
        with pytest.raises(PermissionError):
            os.replace(candidate, target)
        assert target.read_bytes() == before and candidate.read_bytes() == b"candidate"
    finally:
        kernel.CloseHandle(handle)
