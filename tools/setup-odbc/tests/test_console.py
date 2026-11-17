from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from setup_odbc import console


@pytest.fixture
def owned_console(monkeypatch):
    monkeypatch.setattr(console, "sys", SimpleNamespace(platform="win32", frozen=True))
    for name in ("CI", "GITHUB_ACTIONS", "TF_BUILD", "PYTEST_CURRENT_TEST"):
        monkeypatch.delenv(name, raising=False)
    for name in ("stdin", "stdout", "stderr"):
        setattr(console.sys, name, Mock(isatty=Mock(return_value=True)))
    detection = Mock(return_value=True)
    monkeypatch.setattr(console, "_owns_windows_console", detection)
    return detection


def test_owned_console_pauses(owned_console, monkeypatch):
    # pytest sets this again between the fixture and the test call.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert console.should_pause()
    owned_console.assert_called_once()


@pytest.mark.parametrize("stream", ["stdin", "stdout", "stderr"])
def test_redirected_stream_never_pauses(owned_console, monkeypatch, stream):
    monkeypatch.setattr(console.sys, stream, Mock(isatty=Mock(return_value=False)))
    assert not console.should_pause()
    owned_console.assert_not_called()


@pytest.mark.parametrize("variable", ["CI", "GITHUB_ACTIONS", "TF_BUILD", "PYTEST_CURRENT_TEST"])
def test_ci_never_pauses(owned_console, monkeypatch, variable):
    monkeypatch.setenv(variable, "true")
    assert not console.should_pause()
    owned_console.assert_not_called()


def test_existing_terminal_does_not_pause(owned_console):
    owned_console.return_value = False
    assert not console.should_pause()


def test_failed_detection_does_not_pause(owned_console):
    owned_console.side_effect = OSError("No console")
    assert not console.should_pause()


def test_source_does_not_pause(owned_console, monkeypatch):
    monkeypatch.setattr(console.sys, "frozen", False)
    assert not console.should_pause()
    owned_console.assert_not_called()


@pytest.mark.parametrize("code", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("pause", [False, True])
def test_exit_status_preserved(monkeypatch, code, pause):
    monkeypatch.setattr(console, "should_pause", lambda: pause)
    monkeypatch.setattr(console, "main", lambda argv: code)
    prompt = Mock(return_value="")
    monkeypatch.setattr("builtins.input", prompt)
    assert console.run_cli([]) == code
    assert prompt.call_count == int(pause)
    if pause:
        prompt.assert_called_once_with("Press Enter to close this window...")


@pytest.mark.parametrize("arguments,code", [(["--help"], 0), (["invalid"], 2), (["--config", "x"], 2)])
def test_argparse_also_pauses(monkeypatch, arguments, code):
    monkeypatch.setattr(console, "should_pause", lambda: True)
    prompt = Mock(return_value="")
    monkeypatch.setattr("builtins.input", prompt)
    assert console.run_cli(arguments) == code
    prompt.assert_called_once()


@pytest.mark.parametrize("failure", [EOFError, OSError, KeyboardInterrupt])
def test_pause_cancellation_preserves_code(monkeypatch, failure):
    monkeypatch.setattr(console, "should_pause", lambda: True)
    monkeypatch.setattr(console, "main", lambda argv: 4)
    monkeypatch.setattr("builtins.input", Mock(side_effect=failure))
    assert console.run_cli([]) == 4
