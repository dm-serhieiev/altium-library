from pathlib import Path
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import replace
from unittest.mock import Mock

import pytest
import requests

from inventree_sync.api import APIError
from inventree_sync.cli import main
from inventree_sync.config import load_config

EXAMPLE = Path(__file__).parents[2] / "config.example.toml"


@pytest.fixture(autouse=True)
def interactive_auth(monkeypatch, runtime_auth, export_config):
    monkeypatch.setattr("inventree_sync.cli.configuration_directory", lambda: export_config.parent)
    monkeypatch.setattr("builtins.input", lambda prompt: runtime_auth.username)
    monkeypatch.setattr("inventree_sync.cli.getpass.getpass", lambda prompt: runtime_auth.password)
    return runtime_auth


@pytest.fixture
def source_dataset(monkeypatch, export_dataset):
    retrieval = Mock(return_value=export_dataset)
    monkeypatch.setattr("inventree_sync.cli.retrieve_dataset", retrieval)
    return retrieval


def test_cli_configuration_error(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("INVENTREE_API_TOKEN", raising=False)
    path = tmp_path / "config.toml"
    monkeypatch.setattr("inventree_sync.cli.configuration_directory", lambda: tmp_path)
    path.write_text(EXAMPLE.read_text(encoding="utf-8").replace('auth = "basic"', 'auth = "token"'), encoding="utf-8")
    assert main(["validate"]) == 2
    assert "Configuration error" in capsys.readouterr().err


def test_installed_module_entry_point():
    result = subprocess.run([sys.executable, "-m", "inventree_sync", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert all(command in result.stdout for command in ("inspect", "validate", "sync"))


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("command", ["validate", "inspect"])
def test_read_only_commands_without_modifying_files(export_config, source_dataset, tmp_path, capsys, existing, command):
    output = load_config(export_config).sync.output
    if existing:
        output.parent.mkdir()
        output.write_bytes(b"previous database must remain unchanged")
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert main([command]) == 0
    result = capsys.readouterr()
    assert result.err == ""
    if command == "validate":
        assert all(text in result.out for text in (
            "Validation successful", "Tables: 1", "Components: 2", "Referenced symbol libraries: 1",
            "Referenced footprint libraries: 1", "SQLite schema: valid", "binary models not inspected", "No database files modified",
        ))
    else:
        assert "Parts retrieved: 2" in result.out
    assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert source_dataset.call_args.args[0] == load_config(export_config)
    assert source_dataset.call_args.kwargs["auth"].username == "test-user"


def test_sync_publishes_real_sqlite_database(export_config, source_dataset, capsys):
    assert main(["sync"]) == 0
    destination = load_config(export_config).sync.output
    with closing(sqlite3.connect(destination)) as connection:
        assert connection.execute('SELECT count(*) FROM "Resistors"').fetchone() == (2,)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    result = capsys.readouterr()
    assert result.err == ""
    assert all(text in result.out for text in (
        "Synchronization successful", str(destination), "Tables created: 1", "Components exported: 2", "Database integrity: OK", "Publication: successful",
    ))


@pytest.mark.parametrize("command", ["validate", "sync"])
def test_missing_export_sections_fail_before_http(export_config, source_dataset, capsys, command):
    export_config.write_text(export_config.read_text(encoding="utf-8").split("[sync]")[0], encoding="utf-8")
    assert main([command]) == 2
    assert "require [sync]" in capsys.readouterr().err
    source_dataset.assert_not_called()


def test_inspect_accepts_minimal_configuration(export_config, source_dataset, capsys):
    export_config.write_text(export_config.read_text(encoding="utf-8").split("[sync]")[0], encoding="utf-8")
    assert main(["inspect"]) == 0
    assert "Nested parameter retrieval: used" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["validate", "sync"])
def test_invalid_source_does_not_modify_destination(export_config, source_dataset, export_dataset, capsys, command):
    destination = load_config(export_config).sync.output
    destination.parent.mkdir()
    destination.write_bytes(b"previous")
    parameters = {**export_dataset.parameters[20], 10: replace(export_dataset.parameters[20][10], data="malformed")}
    source_dataset.return_value = replace(export_dataset, parameters={**export_dataset.parameters, 20: parameters})
    assert main([command]) == 2
    assert "Part pk=20" in capsys.readouterr().err
    assert destination.read_bytes() == b"previous"
    assert [p.name for p in destination.parent.iterdir()] == [destination.name]


@pytest.mark.parametrize("command", ["validate", "sync"])
def test_missing_library_has_useful_error(export_config, source_dataset, library_layout, capsys, command):
    (library_layout.symbols_dir / "Passives.SchLib").unlink()
    assert main([command]) == 2
    assert "Missing library file" in capsys.readouterr().err


@pytest.mark.parametrize("failure,code,label", [(APIError("HTTP 401"), 3, "API error"), (RuntimeError("internal-secret"), 1, "Unexpected failure")])
def test_full_workflow_source_errors(export_config, source_dataset, capsys, failure, code, label):
    source_dataset.side_effect = failure
    assert main(["sync"]) == code
    result = capsys.readouterr()
    assert label in result.err and "internal-secret" not in result.err
    assert "successful" not in result.out.lower()


def test_filesystem_failure_has_exit_code_four(export_config, source_dataset, monkeypatch, capsys):
    monkeypatch.setattr("inventree_sync.sqlite.os.replace", Mock(side_effect=PermissionError("file locked")))
    assert main(["sync"]) == 4
    result = capsys.readouterr()
    assert "Database error" in result.err and "file locked" in result.err
    assert "successful" not in result.out.lower()


@pytest.mark.parametrize("command", ["validate", "sync"])
def test_missing_credentials_and_no_secret_output(export_config, monkeypatch, runtime_token, capsys, command):
    export_config.write_text(export_config.read_text(encoding="utf-8").replace("[inventree]", '[inventree]\nauth = "token"'), encoding="utf-8")
    monkeypatch.delenv("INVENTREE_API_TOKEN")
    assert main([command]) == 2
    result = capsys.readouterr()
    assert "environment variable" in result.err
    assert runtime_token not in result.err + result.out


@pytest.mark.parametrize("command", ["validate", "sync"])
def test_complete_cli_with_only_mocked_http(export_config, export_dataset, monkeypatch, runtime_token, capsys, command):
    session = Mock()
    monkeypatch.setattr(requests, "Session", Mock(return_value=session))
    categories = [{"pk": c.pk, "name": c.name, "parent": c.parent_pk} for c in export_dataset.tree.categories.values()]
    parts = []
    for part in export_dataset.parts.values():
        parameters = []
        for parameter in export_dataset.parameters[part.pk].values():
            template = export_dataset.templates[parameter.template_pk]
            parameters.append({
                "pk": parameter.pk, "model_id": part.pk, "template": template.pk, "data": parameter.data,
                "template_detail": {"pk": template.pk, "name": template.name, "units": template.units},
            })
        parts.append({"pk": part.pk, "IPN": part.ipn, "category": part.category_pk, "parameters": parameters})
    responses = [Mock(status_code=200, headers={}), Mock(status_code=200, headers={})]
    responses[0].json.return_value = categories
    responses[1].json.return_value = parts
    session.get.side_effect = responses
    assert main([command]) == 0
    assert session.get.call_count == 2
    session.close.assert_called_once()
    result = capsys.readouterr()
    assert runtime_token not in result.out + result.err
    assert "Authorization" not in result.out + result.err
    assert load_config(export_config).sync.output.exists() == (command == "sync")


@pytest.mark.parametrize("command", ["validate", "sync"])
@pytest.mark.parametrize("extension", [".accdb", ".db", ".SchLib", ".txt", ""])
def test_invalid_output_extension_fails_before_retrieval(export_config, source_dataset, tmp_path, capsys, command, extension):
    export_config.write_text(export_config.read_text(encoding="utf-8").replace("components.sqlite", "components" + extension), encoding="utf-8")
    destination = load_config(export_config).sync.output
    destination.parent.mkdir()
    destination.write_bytes(b"unrelated existing file")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert main([command]) == 2
    result = capsys.readouterr()
    assert "Configuration error" in result.err and ".sqlite or .sqlite3" in result.err
    assert "successful" not in result.out.lower()
    source_dataset.assert_not_called()
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("extension", [".sqlite3", ".SQLITE", ".SQLITE3"])
def test_sync_supported_output_extensions(export_config, source_dataset, capsys, extension):
    export_config.write_text(export_config.read_text(encoding="utf-8").replace("components.sqlite", "components" + extension), encoding="utf-8")
    assert main(["sync"]) == 0
    destination = load_config(export_config).sync.output
    with closing(sqlite3.connect(destination)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert "Synchronization successful" in capsys.readouterr().out
    assert [path.name for path in destination.parent.iterdir()] == [destination.name]


def test_inspect_does_not_require_valid_export_extension(export_config, source_dataset, capsys):
    export_config.write_text(export_config.read_text(encoding="utf-8").replace("components.sqlite", "components.accdb"), encoding="utf-8")
    assert main(["inspect"]) == 0
    assert "Nested parameter retrieval: used" in capsys.readouterr().out


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_journal_conflict_reports_exit_code_four_and_preserves_files(export_config, source_dataset, tmp_path, capsys, suffix):
    assert main(["sync"]) == 0
    capsys.readouterr()
    destination = load_config(export_config).sync.output
    sidecar = Path(str(destination) + suffix)
    sidecar.write_bytes(b"another SQLite consumer's sidecar")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert main(["sync"]) == 4
    result = capsys.readouterr()
    assert "Database error" in result.err and str(sidecar) in result.err
    assert "publication blocked" in result.err and "successful" not in result.out.lower()
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("command", [[], ["sync"], ["validate"], ["inspect"]])
def test_default_discovery_and_single_credential_prompt(export_config, source_dataset, monkeypatch, runtime_auth, capsys, command):
    username = Mock(return_value=runtime_auth.username)
    password = Mock(return_value=runtime_auth.password)
    monkeypatch.setattr("builtins.input", username)
    monkeypatch.setattr("inventree_sync.cli.getpass.getpass", password)
    monkeypatch.setattr("inventree_sync.cli.configuration_directory", lambda: export_config.parent)
    # Discovery expects config.toml; this fixture already uses that filename.
    assert main(command) == 0
    username.assert_called_once_with("Username: ")
    password.assert_called_once_with("Password: ")
    assert source_dataset.call_args.kwargs["auth"].password == runtime_auth.password
    result = capsys.readouterr()
    assert runtime_auth.password not in result.out + result.err
    assert "Username: test-user" not in result.out


@pytest.mark.parametrize("failure", [EOFError, OSError, KeyboardInterrupt])
def test_unavailable_interactive_input_fails_safely(export_config, source_dataset, monkeypatch, capsys, failure):
    monkeypatch.setattr("builtins.input", Mock(side_effect=failure))
    assert main(["inspect"]) == 2
    assert "interactive credential input" in capsys.readouterr().err
    source_dataset.assert_not_called()


def test_password_fallback_is_rejected_before_echo(export_config, source_dataset, monkeypatch, capsys):
    import getpass
    import warnings

    def insecure_fallback(prompt):
        warnings.warn("Password input may be echoed", getpass.GetPassWarning)
        pytest.fail("Unprotected fallback must not execute")
    monkeypatch.setattr("inventree_sync.cli.getpass.getpass", insecure_fallback)
    assert main(["inspect"]) == 2
    assert "interactive credential input" in capsys.readouterr().err
    source_dataset.assert_not_called()


@pytest.mark.parametrize("username,password,reason", [("", "unused", "Username"), ("user", "", "Password")])
def test_empty_interactive_credentials(export_config, source_dataset, monkeypatch, capsys, username, password, reason):
    monkeypatch.setattr("builtins.input", lambda prompt: username)
    monkeypatch.setattr("inventree_sync.cli.getpass.getpass", lambda prompt: password)
    assert main(["inspect"]) == 2
    assert reason in capsys.readouterr().err
    source_dataset.assert_not_called()


def test_help_never_prompts_or_initializes_config(monkeypatch, capsys):
    monkeypatch.setattr("inventree_sync.cli.configuration_directory", lambda: pytest.fail("Help must not discover config"))
    with pytest.raises(SystemExit) as done:
        main(["--help"])
    assert done.value.code == 0
    assert "--config" not in capsys.readouterr().out


@pytest.mark.parametrize("arguments", [["--config", "arbitrary.toml"], ["inspect", "--config", "arbitrary.toml"]])
def test_cli_rejects_config_override(monkeypatch, arguments):
    monkeypatch.setattr("inventree_sync.cli.configuration_directory", lambda: pytest.fail("No config lookup"))
    with pytest.raises(SystemExit) as done:
        main(arguments)
    assert done.value.code == 2


@pytest.mark.parametrize("command", [[], ["sync"], ["inspect"], ["validate"]])
def test_missing_config_never_reads_example_or_prompts(tmp_path, monkeypatch, capsys, command):
    monkeypatch.setattr("inventree_sync.cli.configuration_directory", lambda: tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("No first-run prompts"))
    (tmp_path / "config.example.toml").write_text("not valid TOML", encoding="utf-8")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert main(command) == 2
    error = capsys.readouterr().err
    assert "Configuration file not found:" in error and str(tmp_path / "config.toml") in error
    assert "same directory as inventree-sync.exe" in error and "tools/README.md" in error
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("failure", [APIError("HTTP 401"), APIError("Connection failed")])
def test_api_failure_preserves_offline_snapshot(export_config, source_dataset, capsys, existing, failure):
    destination = load_config(export_config).sync.output
    if existing:
        destination.parent.mkdir()
        destination.write_bytes(b"previous snapshot")
    source_dataset.side_effect = failure
    assert main([]) == 3
    output = capsys.readouterr()
    assert "Synchronization successful" not in output.out
    assert ("remains available for offline use" in output.err) == existing
    if existing:
        assert destination.read_bytes() == b"previous snapshot"
    else:
        assert not destination.exists()


def test_api_failure_code_survives_unavailable_snapshot_stat(export_config, source_dataset, monkeypatch, capsys):
    source_dataset.side_effect = APIError("Connection failed")
    monkeypatch.setattr(Path, "is_file", Mock(side_effect=PermissionError))
    assert main([]) == 3
    error = capsys.readouterr().err
    assert "API error" in error and "remains available" not in error
