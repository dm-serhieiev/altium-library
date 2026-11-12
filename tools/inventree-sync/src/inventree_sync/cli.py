"""Inspect source data, validate complete exports, or publish SQLite snapshots."""

import argparse
import sys

from .adapters import AdapterError
from .api import APIError
from .categories import CategoryError
from .config import ConfigError, load_config, require_export_settings
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="inventree-sync")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "validate", "sync"):
        command = commands.add_parser(name)
        command.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            dataset = retrieve_dataset(args.config)
            _print_summary(dataset)
            return 0
        config = load_config(args.config)
        sync, libraries = require_export_settings(config)
        dataset = retrieve_dataset(config.source)
        layout = LibraryLayout(sync.dblib, libraries.symbols, libraries.footprints)
        prepared = prepare_tables(dataset, layout)
        components = sum(len(table.rows) for table in prepared.tables)
        if args.command == "validate":
            validate_sqlite_tables(prepared)
            print("Validation successful\n")
            print(f"Root category: {dataset.tree.full_path(dataset.root_category_pk)}")
            print(f"Tables: {len(prepared.tables)}")
            print(f"Components: {components}")
            for kind, field in (("symbol", "Library Path"), ("footprint", "Footprint Path")):
                count = len({row[field] for table in prepared.tables for row in table.rows})
                print(f"Referenced {kind} libraries: {count}")
            print("SQLite schema: valid\nAltium references: valid (library files checked; binary models not inspected)\nNo database files modified")
        else:
            write_sqlite_database(prepared, sync.output)
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
