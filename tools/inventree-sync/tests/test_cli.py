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

EXAMPLE = Path(__file__).parents[1] / "config.example.toml"


@pytest.fixture
def source_dataset(monkeypatch, export_dataset):
    retrieval = Mock(return_value=export_dataset)
    monkeypatch.setattr("inventree_sync.cli.retrieve_dataset", retrieval)
    return retrieval


def test_cli_configuration_error(monkeypatch, capsys):
    monkeypatch.delenv("INVENTREE_API_TOKEN", raising=False)
    assert main(["validate", "--config", str(EXAMPLE)]) == 2
    assert "Configuration error" in capsys.readouterr().err


def test_installed_module_entry_point():
    result = subprocess.run([sys.executable, "-m", "inventree_sync", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert all(command in result.stdout for command in ("inspect", "validate", "sync"))


@pytest.mark.parametrize("existing", [False, True])
def test_validate_full_export_without_modifying_files(export_config, source_dataset, tmp_path, capsys, existing):
    output = load_config(export_config).sync.output
    if existing:
        output.parent.mkdir()
        output.write_bytes(b"previous database must remain unchanged")
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert main(["validate", "--config", str(export_config)]) == 0
    result = capsys.readouterr()
    assert result.err == ""
    assert all(text in result.out for text in (
        "Validation successful", "Tables: 1", "Components: 2", "Referenced symbol libraries: 1",
        "Referenced footprint libraries: 1", "SQLite schema: valid", "binary models not inspected", "No database files modified",
    ))
    assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    source_dataset.assert_called_once_with(export_config.resolve())


def test_sync_publishes_real_sqlite_database(export_config, source_dataset, capsys):
    assert main(["sync", "--config", str(export_config)]) == 0
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
    assert main([command, "--config", str(export_config)]) == 2
    assert "require [sync]" in capsys.readouterr().err
    source_dataset.assert_not_called()


def test_inspect_accepts_minimal_configuration(export_config, source_dataset, capsys):
    export_config.write_text(export_config.read_text(encoding="utf-8").split("[sync]")[0], encoding="utf-8")
    assert main(["inspect", "--config", str(export_config)]) == 0
    assert "Nested parameter retrieval: used" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["validate", "sync"])
def test_invalid_source_does_not_modify_destination(export_config, source_dataset, export_dataset, capsys, command):
    destination = load_config(export_config).sync.output
    destination.parent.mkdir()
    destination.write_bytes(b"previous")
    parameters = {**export_dataset.parameters[20], 10: replace(export_dataset.parameters[20][10], data="malformed")}
    source_dataset.return_value = replace(export_dataset, parameters={**export_dataset.parameters, 20: parameters})
    assert main([command, "--config", str(export_config)]) == 2
    assert "Part pk=20" in capsys.readouterr().err
    assert destination.read_bytes() == b"previous"
    assert [p.name for p in destination.parent.iterdir()] == [destination.name]


@pytest.mark.parametrize("command", ["validate", "sync"])
def test_missing_library_has_useful_error(export_config, source_dataset, library_layout, capsys, command):
    (library_layout.symbols_dir / "Passives.SchLib").unlink()
    assert main([command, "--config", str(export_config)]) == 2
    assert "Missing library file" in capsys.readouterr().err


@pytest.mark.parametrize("failure,code,label", [(APIError("HTTP 401"), 3, "API error"), (RuntimeError("internal-secret"), 1, "Unexpected failure")])
def test_full_workflow_source_errors(export_config, source_dataset, capsys, failure, code, label):
    source_dataset.side_effect = failure
    assert main(["sync", "--config", str(export_config)]) == code
    result = capsys.readouterr()
    assert label in result.err and "internal-secret" not in result.err
    assert result.out == ""


def test_filesystem_failure_has_exit_code_four(export_config, source_dataset, monkeypatch, capsys):
    monkeypatch.setattr("inventree_sync.sqlite.os.replace", Mock(side_effect=PermissionError("file locked")))
    assert main(["sync", "--config", str(export_config)]) == 4
    result = capsys.readouterr()
    assert "Database error" in result.err and "file locked" in result.err
    assert result.out == ""


@pytest.mark.parametrize("command", ["validate", "sync"])
def test_missing_credentials_and_no_secret_output(export_config, monkeypatch, runtime_token, capsys, command):
    monkeypatch.delenv("INVENTREE_API_TOKEN")
    assert main([command, "--config", str(export_config)]) == 2
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
    assert main([command, "--config", str(export_config)]) == 0
    assert session.get.call_count == 2
    session.close.assert_called_once()
    result = capsys.readouterr()
    assert runtime_token not in result.out + result.err
    assert "Authorization" not in result.out + result.err
    assert load_config(export_config).sync.output.exists() == (command == "sync")
