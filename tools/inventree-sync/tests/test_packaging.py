"""Opt-in smoke tests run by build.ps1 against the real Windows executable."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

import pytest


@pytest.fixture
def packaged_repo(request, tmp_path):
    option = request.config.getoption("--sync-executable")
    if not option or sys.platform != "win32":
        pytest.skip("Windows executable smoke tests run with --sync-executable after building")
    root = tmp_path / "Repository with spaces"
    tool = root / "tools" / "inventree-sync"
    (tool / "dist").mkdir(parents=True)
    source = Path(__file__).parents[1]
    shutil.copy2(option, tool / "dist" / "inventree-sync.exe")
    for name in ("config.example.toml", "launch.ps1"):
        shutil.copy2(source / name, tool / name)
    shutil.copy2(source.parents[1] / "sync.cmd", root / "sync.cmd")
    return root, tool


def runtime_environment():
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PYTHON") and key.upper() not in {"VIRTUAL_ENV", "INVENTREE_API_TOKEN"}}
    system = Path(os.environ["SystemRoot"]) / "System32"
    env["PATH"] = str(system) + os.pathsep + str(system / "WindowsPowerShell" / "v1.0")
    return env


def launcher_command(root, *arguments):
    # cmd /s /c requires an outer pair of quotes when both the batch pathname
    # and an argument contain spaces. Avoid Python's extra list quoting here.
    command = subprocess.list2cmdline([str(root / "sync.cmd"), *arguments])
    return f'{os.environ["COMSPEC"]} /d /s /c "{command}"'


def test_executable_help_and_launcher_exit_codes_without_python(packaged_repo, tmp_path):
    root, tool = packaged_repo
    exe = tool / "dist" / "inventree-sync.exe"
    for command in ([str(exe), "--help"], launcher_command(root, "--help")):
        result = subprocess.run(command, cwd=tmp_path, env=runtime_environment(), capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert "--config" in result.stdout
        assert not (tool / "config.toml").exists()
    result = subprocess.run(launcher_command(root, "inspect", "--config", str(tmp_path / "missing.toml")), cwd=tmp_path, env=runtime_environment(), capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and "Configuration error" in result.stderr
    settings = tmp_path / "Settings with spaces"
    settings.mkdir()
    config = settings / "inspection.toml"
    config.write_text('[inventree]\nbase_url="http://127.0.0.1:9"\n[scope]\nroot_category_path=["Components"]\n', encoding="utf-8")
    result = subprocess.run(launcher_command(root, "inspect", "--config", str(config)), input="\n", cwd=tmp_path, env=runtime_environment(), capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and "Username must be nonempty" in result.stderr
    assert "Server: http://127.0.0.1:9" in result.stdout
    exe.unlink()
    result = subprocess.run(launcher_command(root), cwd=tmp_path, env=runtime_environment(), capture_output=True, text=True, timeout=30)
    assert result.returncode == 4 and "Missing executable" in result.stderr


def test_frozen_first_run_uses_external_config_from_unrelated_cwd(packaged_repo, tmp_path):
    _, tool = packaged_repo
    result = subprocess.run([str(tool / "dist" / "inventree-sync.exe"), "inspect"], input="http://127.0.0.1:9\n\n\n", cwd=tmp_path, env=runtime_environment(), capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and "Username" in result.stdout
    assert "Username must be nonempty" in result.stderr
    source = tool / "config.toml"
    raw = tomllib.loads(source.read_text(encoding="utf-8"))
    example = tomllib.loads((tool / "config.example.toml").read_text(encoding="utf-8"))
    assert raw["inventree"]["base_url"] == "http://127.0.0.1:9"
    assert raw["libraries"] == example["libraries"] and raw["sync"] == example["sync"]
    assert not {"password", "username", "token"} & set(raw["inventree"])


def test_frozen_secure_console_authentication_and_read_only_api(packaged_repo, tmp_path):
    _, tool = packaged_repo
    # A separate driver owns a hidden Windows console and types synthetic input
    # through CONIN$, exercising real getpass instead of an insecure stdin fallback.
    driver = Path(__file__).with_name("windows_console_smoke.py")
    result = subprocess.run([sys.executable, str(driver), str(tool / "dist" / "inventree-sync.exe"), str(tool / "config.toml")], cwd=tmp_path, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=45)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["returncode"] == 0, report["stderr"]
    assert report["authenticated_requests"] == 2
    assert report["password_leaked"] is False
    assert report["credentials_persisted"] is False
    assert "Parts retrieved: 1" in report["stdout"]
