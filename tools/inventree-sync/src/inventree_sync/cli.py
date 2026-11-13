"""Inspect source data, validate complete exports, or publish SQLite snapshots."""

import argparse
import getpass
import sys
import warnings

from requests.auth import HTTPBasicAuth

from .adapters import AdapterError
from .api import APIError
from .categories import CategoryError
from .config import ConfigError, configuration_directory, initialize_config, load_config, require_export_settings
from .retrieval import DatasetError, PreparedDataset, retrieve_dataset
from .sqlite import DatabaseError, validate_sqlite_tables, write_sqlite_database
from .transform import LibraryLayout, prepare_tables
from .validate import ExportValidationError


def _print_summary(dataset: PreparedDataset) -> None:
    root = dataset.tree.categories[dataset.root_category_pk]
    print(f"Root category: {root.name!r} (PK {root.pk})")
    print(f"Root path: {dataset.tree.full_path(root.pk)!r}")
    print(f"Categories in subtree: {len(dataset.scope_category_pks)}")
    print(f"Parts retrieved: {len(dataset.parts)}")
    print(f"Exported leaf categories: {len(dataset.groups)}")
    print(f"Part parameters: {sum(len(values) for values in dataset.parameters.values())}")
    print(f"Distinct ParameterTemplates: {len(dataset.templates)}")
    print("Nested parameter retrieval: used (parameters=true, template_detail)")


def _prompt_auth() -> HTTPBasicAuth:
    try:
        username = input("Username: ")
        if not username.strip() or ":" in username:
            raise ConfigError("Username must be nonempty and must not contain a colon")
        # Abort before getpass's fallback can read an echoed password.
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Password: ")
        if not password:
            raise ConfigError("Password must not be empty")
    except (EOFError, OSError, KeyboardInterrupt, getpass.GetPassWarning):
        raise ConfigError("Secure interactive credential input is unavailable or cancelled; run from an interactive console") from None
    return HTTPBasicAuth(username, password)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="inventree-sync")
    parser.add_argument("command", nargs="?", choices=("sync", "validate", "inspect"), default="sync", help="sync (default), validate without publication, or inspect source data")
    parser.add_argument("--config", help="TOML path; defaults to the external application/repository config.toml")
    args = parser.parse_args(argv)
    try:
        print("InvenTree Synchronization\n--------------------------------", flush=True)
        if args.config is not None:
            config = load_config(args.config)
        else:
            directory = configuration_directory()
            config = initialize_config(directory / "config.toml", directory / "config.example.toml")
        if args.command != "inspect":
            sync, libraries = require_export_settings(config)
        print(f"Server: {config.inventree.base_url}", flush=True)
        auth = _prompt_auth() if config.inventree.auth == "basic" else None
        print("Retrieving categories and components...", flush=True)
        dataset = retrieve_dataset(config, auth=auth)
        print("Retrieving categories and components... OK", flush=True)
        if args.command == "inspect":
            _print_summary(dataset)
            return 0
        layout = LibraryLayout(sync.dblib, libraries.symbols, libraries.footprints)
        print("Preparing component tables...", flush=True)
        prepared = prepare_tables(dataset, layout)
        print("Preparing component tables... OK", flush=True)
        components = sum(len(table.rows) for table in prepared.tables)
        if args.command == "validate":
            print("Validating SQLite schema and data...", flush=True)
            validate_sqlite_tables(prepared)
            print("Validating SQLite schema and data... OK", flush=True)
            print("Validation successful\n")
            print(f"Root category: {dataset.tree.full_path(dataset.root_category_pk)}")
            print(f"Tables: {len(prepared.tables)}")
            print(f"Components: {components}")
            for kind, field in (("symbol", "Library Path"), ("footprint", "Footprint Path")):
                count = len({row[field] for table in prepared.tables for row in table.rows})
                print(f"Referenced {kind} libraries: {count}")
            print("SQLite schema: valid\nAltium references: valid (library files checked; binary models not inspected)\nNo database files modified")
        else:
            print("Validating data, generating and publishing SQLite database...", flush=True)
            write_sqlite_database(prepared, sync.output)
            print("Validating data, generating and publishing SQLite database... OK", flush=True)
            print("Synchronization successful\n")
            print(f"Database: {sync.output}")
            print(f"Tables created: {len(prepared.tables)}")
            print(f"Components exported: {components}")
            print("Database integrity: OK\nPublication: successful")
        return 0
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except (APIError, AdapterError) as exc:
        print(f"API error: {exc}", file=sys.stderr)
        return 3
    except (CategoryError, DatasetError, ExportValidationError) as exc:
        print(f"Data validation error: {exc}", file=sys.stderr)
        return 2
    except DatabaseError as exc:
        print(f"Database error: {exc}", file=sys.stderr)
        return 4
    except Exception:
        # Unexpected errors may contain request objects, tokens or raw payloads.
        print(f"Unexpected failure; {args.command} did not complete", file=sys.stderr)
        return 1
