from pathlib import Path
import subprocess
import sys

import pytest

from inventree_sync.cli import main

EXAMPLE = Path(__file__).parents[1] / "config.example.toml"


@pytest.mark.parametrize("command", ["validate", "sync"])
def test_commands_explicitly_incomplete(command, runtime_token, capsys):
    assert main([command, "--config", str(EXAMPLE)]) == 1
    output = capsys.readouterr()
    assert "not implemented" in output.err
    assert runtime_token not in output.err
    assert output.out == ""


def test_cli_configuration_error(monkeypatch, capsys):
    monkeypatch.delenv("INVENTREE_API_TOKEN", raising=False)
    assert main(["validate", "--config", str(EXAMPLE)]) == 2
    assert "Configuration error" in capsys.readouterr().err


def test_installed_module_entry_point():
    result = subprocess.run([sys.executable, "-m", "inventree_sync", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "validate" in result.stdout and "sync" in result.stdout
