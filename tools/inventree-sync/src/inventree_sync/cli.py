"""CLI shell; never claim full validation or synchronization at milestone 1A."""

import argparse
import sys

from .config import ConfigError, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="inventree-sync")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "sync"):
        command = commands.add_parser(name)
        command.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    try:
        load_config(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    print(
        f"{args.command}: not implemented beyond configuration in Milestone 1A; "
        "the read layer is available as a Python API. No full validation or synchronization was performed.",
        file=sys.stderr,
    )
    return 1
