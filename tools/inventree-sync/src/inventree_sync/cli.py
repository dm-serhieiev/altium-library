"""Read-only inspection; full validation and synchronization remain unimplemented."""

import argparse
import sys

from .adapters import AdapterError
from .api import APIError
from .categories import CategoryError
from .config import ConfigError, load_config
from .retrieval import DatasetError, PreparedDataset, retrieve_dataset


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
        load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except (APIError, AdapterError) as exc:
        print(f"API error: {exc}", file=sys.stderr)
        return 3
    except (CategoryError, DatasetError) as exc:
        print(f"Data validation error: {exc}", file=sys.stderr)
        return 2
    except Exception:
        # Unexpected errors may contain request objects, tokens or raw payloads.
        print("Unexpected failure; inspection did not complete", file=sys.stderr)
        return 1
    print(
        f"{args.command}: not implemented beyond configuration; "
        "use inspect for read-only retrieval. No full validation or synchronization was performed.",
        file=sys.stderr,
    )
    return 1
