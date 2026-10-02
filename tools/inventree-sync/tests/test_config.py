from dataclasses import asdict
from pathlib import Path

import pytest

from inventree_sync.config import ConfigError, InvenTreeSettings, load_config


def write_config(tmp_path, server='', scope='root_category_path = ["Components", "Passives"]'):
    path = tmp_path / "settings.toml"
    path.write_text('[inventree]\nbase_url = "https://inventree.example.com"\n' + server + '\n[scope]\n' + scope, encoding="utf-8")
    return path


def test_config_contains_no_credentials(tmp_path, runtime_token, monkeypatch):
    path = write_config(tmp_path, 'auth = "token"\nretries = 2')
    monkeypatch.chdir(tmp_path)
    config = load_config("settings.toml")
    assert config.source == path.resolve()
    assert config.scope.root_category_path == ("Components", "Passives")
    assert config.inventree.retries == 2
    assert runtime_token not in repr(config)
    assert runtime_token not in repr(asdict(config))


def test_missing_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("INVENTREE_API_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="environment variable"):
        load_config(write_config(tmp_path))


def test_custom_environment(tmp_path, monkeypatch, runtime_token):
    monkeypatch.setenv("TEST_SYNC_TOKEN", runtime_token)
    config = load_config(write_config(tmp_path, 'token_env = "TEST_SYNC_TOKEN"'))
    assert config.inventree.token_env == "TEST_SYNC_TOKEN"


@pytest.mark.parametrize("url", ["", "example.com", "ftp://example.com", "https://", "https://example.com:bad", "https://example.com:0", "https://user:password@example.com", "https://example.com?token=hidden", "https://example.com/#fragment", "https://example.com/a/../b", "https://example.com/%2e%2e", "https://example.com/\napi", "https://example.com\\evil"])
def test_invalid_url(url):
    with pytest.raises(ConfigError, match="base_url") as error:
        InvenTreeSettings(url)
    assert "password" not in str(error.value)
    assert "hidden" not in str(error.value)


@pytest.mark.parametrize("settings", [{"auth": "basic"}, {"token_env": ""}, {"token_env": "TOKEN=secret"}, {"retries": True}, {"retries": -1}, {"retries": 1.5}, {"connect_timeout": 0}, {"read_timeout": float("inf")}, {"connect_timeout": float("nan")}, {"read_timeout": "60"}, {"read_timeout": True}])
def test_invalid_settings(settings):
    with pytest.raises(ConfigError):
        InvenTreeSettings("https://inventree.example.com", **settings)


@pytest.mark.parametrize("scope", ['root_category_path = "Components"', 'root_category_path = []', 'root_category_path = [1]', 'root_category_path = [""]', 'root_category_path = ["  "]', 'all = true', 'root_category_path = ["Components"]\nall = true'])
def test_invalid_scope(tmp_path, runtime_token, scope):
    with pytest.raises(ConfigError, match="scope"):
        load_config(write_config(tmp_path, scope=scope))


def test_no_secret_in_bad_toml_error(tmp_path, runtime_token):
    path = tmp_path / "bad.toml"
    path.write_text(f'bad = "{runtime_token}', encoding="utf-8")
    with pytest.raises(ConfigError) as error:
        load_config(path)
    assert runtime_token not in str(error.value)
    assert error.value.__suppress_context__


def test_secret_in_config_rejected(tmp_path, runtime_token):
    with pytest.raises(ConfigError) as error:
        load_config(write_config(tmp_path, f'token = "{runtime_token}"'))
    assert runtime_token not in str(error.value)


def test_example_config(runtime_token):
    config = load_config(Path(__file__).parents[1] / "config.example.toml")
    assert config.scope.root_category_path == ("Electronic Components",)


@pytest.mark.parametrize("content", ["", "inventree = 3", "[inventree]\n[scope]\nroot_category_path = [\"Root\"]"])
def test_missing_sections_and_fields(tmp_path, runtime_token, content):
    path = tmp_path / "empty.toml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="Cannot read"):
        load_config(tmp_path / "missing.toml")

