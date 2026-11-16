"""Opt-in smoke tests run by build.ps1 against the real Windows executable."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.fixture
def packaged_repo(request, tmp_path):
    option = request.config.getoption("--sync-executable")
    if not option or sys.platform != "win32":
        pytest.skip("Windows executable smoke tests run with --sync-executable after building")
    root = tmp_path / "Repository with spaces"
    tool = root / "tools"
    tool.mkdir(parents=True)
    shutil.copy2(option, tool / "inventree-sync.exe")
    return root, tool


def runtime_environment():
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON") and key.upper() not in {"VIRTUAL_ENV", "INVENTREE_API_TOKEN"}}
    system = Path(os.environ["SystemRoot"]) / "System32"
    env["PATH"] = str(system) + os.pathsep + str(system / "WindowsPowerShell" / "v1.0")
    return env


@pytest.mark.parametrize("arguments,code", [(["--help"], 0), (["invalid"], 2), (["--config", "missing.toml"], 2)])
def test_executable_arguments_without_python(packaged_repo, tmp_path, arguments, code):
    _, tool = packaged_repo
    result = subprocess.run([str(tool / "inventree-sync.exe"), *arguments], cwd=tmp_path,
                            env=runtime_environment(), capture_output=True, text=True, timeout=30)
    assert result.returncode == code, result.stderr
    assert "Press Enter" not in result.stdout + result.stderr
    if code == 0:
        assert "--config" not in result.stdout
        assert all(command in result.stdout for command in ("sync", "validate", "inspect"))
    assert not (tool / "config.toml").exists()


def test_only_config_beside_executable_is_used(packaged_repo, tmp_path):
    root, tool = packaged_repo
    legacy = tool / "inventree-sync"
    legacy.mkdir()
    for directory in (tmp_path, root, tool):
        (directory / "config.example.toml").write_text("invalid TOML", encoding="utf-8")
    for directory in (tmp_path, root, legacy):
        (directory / "config.toml").write_text("invalid fallback", encoding="utf-8")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.toml")}
    command = [str(tool / "inventree-sync.exe"), "inspect"]
    result = subprocess.run(command, cwd=tmp_path, env=runtime_environment(), input="",
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert "Configuration file not found:" in result.stderr
    assert str(tool / "config.toml") in result.stderr and "tools/README.md" in result.stderr
    assert "Username" not in result.stdout and "Press Enter" not in result.stdout
    assert {p: p.read_bytes() for p in tmp_path.rglob("*.toml")} == before
    source = tool / "config.toml"
    source.write_text('[inventree]\nbase_url="http://127.0.0.1:9"\n[scope]\nroot_category_path=["Components"]\n', encoding="utf-8")
    before_config = source.read_bytes()
    result = subprocess.run(command, cwd=tmp_path, env=runtime_environment(), input="\n",
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and "Username must be nonempty" in result.stderr
    assert "Server: http://127.0.0.1:9" in result.stdout
    assert "Press Enter" not in result.stdout and source.read_bytes() == before_config


def test_windows_executable_lock_blocks_atomic_replacement(packaged_repo):
    import ctypes
    from ctypes import wintypes

    _, tool = packaged_repo
    destination = tool / "inventree-sync.exe"
    previous = destination.read_bytes()
    candidate = tool / "candidate.exe"
    candidate.write_bytes(previous + b"candidate")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # A real Windows handle with FILE_SHARE_READ but no FILE_SHARE_DELETE.
    handle = kernel.CreateFileW(str(destination), 0x80000000, 1, None, 3, 0, None)
    assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
    try:
        with pytest.raises(PermissionError):
            os.replace(candidate, destination)
        assert destination.read_bytes() == previous
        assert candidate.read_bytes() == previous + b"candidate"
    finally:
        kernel.CloseHandle(handle)


def test_frozen_secure_console_authentication_and_read_only_api(packaged_repo, tmp_path):
    _, tool = packaged_repo
    # A separate driver owns a hidden Windows console and types synthetic input
    # through CONIN$, exercising real getpass instead of an insecure stdin fallback.
    driver = Path(__file__).with_name("windows_console_smoke.py")
    result = subprocess.run([sys.executable, str(driver), str(tool / "inventree-sync.exe"), str(tool / "config.toml")], cwd=tmp_path, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=45)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["returncode"] == 0, report["stderr"]
    assert report["authenticated_requests"] == 2
    assert report["password_leaked"] is False
    assert report["credentials_persisted"] is False
    assert "Parts retrieved: 1" in report["stdout"]


@pytest.mark.parametrize("mode", ["owned", "terminal", "ci"])
@pytest.mark.parametrize("outcome,code", [("success", 0), ("error", 3)])
def test_real_console_pause_and_exit_codes(packaged_repo, tmp_path, mode, outcome, code):
    _, tool = packaged_repo
    driver = Path(__file__).with_name("windows_pause_smoke.py")
    result = subprocess.run([sys.executable, str(driver), str(tool / "inventree-sync.exe"), mode, outcome],
                            cwd=tmp_path, capture_output=True, text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=75)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["returncode"] == code, report
    assert report["paused"] == (mode == "owned"), report
    assert report["published"] == (outcome == "success"), report
    assert report["success"] == (outcome == "success"), report
    assert report["api_error"] == (outcome == "error"), report
    assert not report["secret_leaked"]
