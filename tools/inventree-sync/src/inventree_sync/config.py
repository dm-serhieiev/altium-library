"""Configuration contains settings and secret references, never secrets."""

from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import tomllib
from urllib.parse import urlsplit


class ConfigError(ValueError):
    """Invalid configuration or missing runtime credentials."""


@dataclass(frozen=True, slots=True)
class InvenTreeSettings:
    base_url: str
    auth: str = "token"
    token_env: str = "INVENTREE_API_TOKEN"
    connect_timeout: float = 10
    read_timeout: float = 60
    retries: int = 3

    def __post_init__(self) -> None:
        validate_base_url(self.base_url)
        if self.auth != "token":
            raise ConfigError("inventree.auth: only token authentication is implemented")
        if not isinstance(self.token_env, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", self.token_env
        ):
            raise ConfigError("inventree.token_env: expected an environment variable name")
        for name in ("connect_timeout", "read_timeout"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ConfigError(f"inventree.{name}: expected a finite positive number")
        if type(self.retries) is not int or self.retries < 0:
            raise ConfigError("inventree.retries: expected a non-negative integer")


@dataclass(frozen=True, slots=True)
class ScopeSettings:
    root_category_path: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.root_category_path or any(
            not isinstance(segment, str) or not segment.strip()
            for segment in self.root_category_path
        ):
            raise ConfigError("scope.root_category_path: expected non-empty name segments")


@dataclass(frozen=True, slots=True)
class Config:
    source: Path
    inventree: InvenTreeSettings
    scope: ScopeSettings


def validate_base_url(value: str) -> None:
    """Accept a server URL (including a deployment subpath), without secrets."""
    try:
        if not isinstance(value, str) or any(c.isspace() for c in value):
            raise ValueError
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "?" in value
            or "#" in value
            or "\\" in value
            or "%" in parsed.netloc
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or any(p in {".", ".."} for p in parsed.path.split("/"))
            or "%" in parsed.path
            or parsed.port == 0
        ):
            raise ValueError
    except (ValueError, TypeError):
        raise ConfigError("inventree.base_url: expected an HTTP(S) server URL without credentials, query or fragment") from None


def read_token(settings: InvenTreeSettings) -> str:
    """Read at the transport boundary; do not cache in the parsed configuration."""
    token = os.environ.get(settings.token_env)
    if not token or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in token):
        raise ConfigError("API token environment variable is missing, empty or invalid")
    return token


def load_config(path: str | Path) -> Config:
    source = Path(path).resolve()
    try:
        with source.open("rb") as stream:
            raw = tomllib.load(stream)
    except (OSError, ValueError):
        # Parser errors can include source lines containing an accidentally pasted secret.
        raise ConfigError(f"Cannot read valid TOML configuration: {source}") from None

    sections: dict[str, dict] = {}
    for name in ("inventree", "scope"):
        section = raw.get(name)
        if not isinstance(section, dict):
            raise ConfigError(f"Configuration requires [{name}]")
        sections[name] = section
    server = sections["inventree"]
    allowed = {"base_url", "auth", "token_env", "connect_timeout", "read_timeout", "retries"}
    if set(server) - allowed:
        raise ConfigError("Unsupported setting in [inventree]; credentials must use environment variables")
    scope = sections["scope"]
    if set(scope) != {"root_category_path"}:
        raise ConfigError("[scope] requires only root_category_path; all-database syntax is not defined")
    root = scope["root_category_path"]
    if not isinstance(root, list):
        raise ConfigError("scope.root_category_path: expected an array of name segments")
    if "base_url" not in server:
        raise ConfigError("inventree.base_url is required")
    settings = InvenTreeSettings(**server)
    result = Config(source, settings, ScopeSettings(tuple(root)))
    read_token(settings)  # Validate availability, but never retain it in Config.
    return result

