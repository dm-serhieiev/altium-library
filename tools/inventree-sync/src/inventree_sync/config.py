"""Configuration contains settings and secret references, never secrets."""

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import sys
import tomllib
from urllib.parse import urlsplit


class ConfigError(ValueError):
    """Invalid configuration or missing runtime credentials."""


@dataclass(frozen=True, slots=True)
class InvenTreeSettings:
    base_url: str
    auth: str = "basic"
    token_env: str = "INVENTREE_API_TOKEN"
    connect_timeout: float = 10
    read_timeout: float = 60
    retries: int = 3

    def __post_init__(self) -> None:
        validate_base_url(self.base_url)
        if self.auth not in {"basic", "token"}:
            raise ConfigError("inventree.auth: expected basic or token")
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
class SyncSettings:
    output: Path
    dblib: Path


@dataclass(frozen=True, slots=True)
class LibrarySettings:
    symbols: Path
    footprints: Path


@dataclass(frozen=True, slots=True)
class Config:
    source: Path
    inventree: InvenTreeSettings
    scope: ScopeSettings
    sync: SyncSettings | None = None
    libraries: LibrarySettings | None = None


def require_export_settings(config: Config) -> tuple[SyncSettings, LibrarySettings]:
    """Inspection still accepts the original two-section configuration."""
    if config.sync is None or config.libraries is None:
        raise ConfigError("validate/sync require [sync] output/dblib and [libraries] symbols/footprints")
    if config.sync.output in (config.source, config.sync.dblib):
        raise ConfigError("sync.output must differ from the configuration and sync.dblib paths")
    if config.sync.output.suffix.casefold() not in {".sqlite", ".sqlite3"}:
        raise ConfigError("sync.output must use a .sqlite or .sqlite3 extension (case-insensitive)")
    return config.sync, config.libraries


def _path_section(raw: dict, name: str, keys: tuple[str, ...], base: Path) -> dict[str, Path] | None:
    if name not in raw:
        return None
    section = raw[name]
    if not isinstance(section, dict) or set(section) != set(keys):
        raise ConfigError(f"[{name}] requires only {', '.join(keys)}")
    paths: dict[str, Path] = {}
    for key in keys:
        value = section[key]
        if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ConfigError(f"{name}.{key}: expected a nonempty filesystem path without controls")
        try:
            paths[key] = (base / value).resolve()
        except (OSError, ValueError):
            raise ConfigError(f"{name}.{key}: cannot resolve filesystem path") from None
    return paths


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

    return _config_from_dict(raw, source)


def _config_from_dict(raw: dict, source: Path) -> Config:
    sections: dict[str, dict] = {}
    if set(raw) - {"inventree", "scope", "sync", "libraries"}:
        raise ConfigError("Unsupported configuration section; only inventree, scope, sync and libraries are supported")
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
    sync = _path_section(raw, "sync", ("output", "dblib"), source.parent)
    libraries = _path_section(raw, "libraries", ("symbols", "footprints"), source.parent)
    result = Config(
        source, settings, ScopeSettings(tuple(root)),
        SyncSettings(**sync) if sync is not None else None,
        LibrarySettings(**libraries) if libraries is not None else None,
    )
    if settings.auth == "token":
        read_token(settings)  # Legacy mode only; never retain a token in Config.
    return result


def configuration_directory() -> Path:
    """Locate external config from source or the frozen executable, never cwd."""
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parents[2]
    executable = Path(sys.executable).resolve()
    for base in executable.parents:
        candidate = base / "tools" / "inventree-sync"
        if (candidate / "config.example.toml").is_file() or (candidate / "config.toml").is_file():
            return candidate
    return executable.parent  # Standalone installation: external example beside exe.


def initialize_config(path: Path, example: Path) -> Config:
    """First run only: retain example paths, exclusively create a credential-free TOML."""
    if path.exists():
        return load_config(path)
    try:
        raw = tomllib.loads(example.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ConfigError(f"First-run setup requires an external config.example.toml: {example}") from None
    defaults = _config_from_dict(raw, path)
    try:
        server = input(f"InvenTree server URL [{defaults.inventree.base_url}]: ") or defaults.inventree.base_url
        root_default = " / ".join(defaults.scope.root_category_path)
        root = input(f"Root category path (levels separated by /) [{root_default}]: ")
    except (EOFError, OSError, KeyboardInterrupt):
        raise ConfigError("First-run setup requires interactive console input; supply an existing --config file") from None
    raw["inventree"]["base_url"] = server
    raw["scope"]["root_category_path"] = [p.strip() for p in root.split("/")] if root else list(defaults.scope.root_category_path)
    result = _config_from_dict(raw, path)
    content = "\n\n".join(
        f"[{section}]\n" + "\n".join(f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in values.items())
        for section, values in raw.items()
    ) + "\n"
    created = False
    try:
        with path.open("x", encoding="utf-8") as stream:
            created = True
            stream.write(content)
    except FileExistsError:
        return load_config(path)  # A concurrent first run won; never overwrite it.
    except OSError:
        if created:
            path.unlink(missing_ok=True)
        raise ConfigError(f"Cannot create first-run configuration: {path}") from None
    return result

