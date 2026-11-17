from unittest.mock import Mock

import pytest

from setup_odbc import cli
from setup_odbc.errors import SetupError


@pytest.fixture
def setup(monkeypatch, snapshot_path, driver):
    monkeypatch.setattr(cli, "require_windows_x64", lambda: None)
    monkeypatch.setattr(cli, "database_path", lambda: snapshot_path)
    monkeypatch.setattr(cli, "installed_drivers", lambda: [driver])
    configure = Mock(return_value="New User DSN created.")
    monkeypatch.setattr(cli, "configure", configure)
    return configure


@pytest.mark.parametrize("check", [False, True])
def test_cli_default_and_check_only(setup, capsys, snapshot_path, driver, check):
    before = snapshot_path.read_bytes()
    assert cli.main(["--check-only"] if check else []) == 0
    setup.assert_called_once_with("AltiumComponents", driver, snapshot_path, check_only=check)
    out, err = capsys.readouterr()
    assert "Connection test:\nSuccessful." in out and "connection is ready" in out
    assert not err and snapshot_path.read_bytes() == before


def test_missing_database_before_driver_or_dsn(setup, snapshot_path, monkeypatch, capsys):
    snapshot_path.unlink()
    drivers = Mock(side_effect=AssertionError("must not enumerate"))
    monkeypatch.setattr(cli, "installed_drivers", drivers)
    assert cli.main([]) == 1
    assert "snapshot not found" in capsys.readouterr().err
    setup.assert_not_called()
    drivers.assert_not_called()


@pytest.mark.parametrize("failure", [SetupError("connection failure"), RuntimeError("private DSN settings"), KeyboardInterrupt()])
def test_failed_setup_never_claims_success(setup, failure, capsys):
    setup.side_effect = failure
    assert cli.main([]) == 1
    out, err = capsys.readouterr()
    assert "Successful" not in out and "ready" not in out
    assert "private DSN settings" not in err and err


def test_alias_forwarded(setup, monkeypatch, driver):
    select = Mock(return_value=driver)
    monkeypatch.setattr(cli, "select_driver", select)
    assert cli.main(["--driver-name", "Compatible SQLite alias"]) == 0
    select.assert_called_once_with("Compatible SQLite alias", [driver])


@pytest.mark.parametrize("args,code", [(["--help"], 0), (["--force"], 2), (["--dsn", "Other"], 2), (["--config", "x"], 2)])
def test_public_arguments_do_not_setup(setup, args, code):
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == code
    setup.assert_not_called()
