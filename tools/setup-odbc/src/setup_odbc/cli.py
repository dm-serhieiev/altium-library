"""Public CLI: one fixed User DSN, no TOML and no InvenTree connection."""

import argparse
import sys

from .database import database_path, snapshot
from .drivers import DEFAULT_DRIVER, installed_drivers, require_windows_x64, select_driver
from .dsn import DSN_NAME, configure
from .errors import SetupError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="setup-odbc", description="Configure the AltiumComponents SQLite User DSN.")
    parser.add_argument("--check-only", action="store_true", help="Verify without changing DSN settings")
    parser.add_argument("--driver-name", default=DEFAULT_DRIVER, help="Exact registered name of a compatible SQLite3 x64 driver")
    args = parser.parse_args(argv)
    print("Altium SQLite ODBC Setup\n------------------------")
    try:
        require_windows_x64()
        path = database_path()
        print(f"\nDatabase:\n{path}", flush=True)
        with snapshot(path):
            drivers = installed_drivers()
            print("\nDetected SQLite ODBC drivers:")
            for driver in drivers:
                print(f"{driver.name} ({driver.bits}-bit)")
            if not drivers:
                print("(none)")
            selected = select_driver(args.driver_name, drivers)
            print(f"\nODBC Driver:\n{selected.name} (64-bit)\n\nDSN:\n{DSN_NAME} (User)", flush=True)
            status = configure(DSN_NAME, selected, path, check_only=args.check_only)
        print(f"\nStatus:\n{status}\n\nConnection test:\nSuccessful.\n\nAltium database connection is ready.")
        return 0
    except SetupError as exc:
        print(f"ODBC setup failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("ODBC setup interrupted. Inspect the User DSN before retrying.", file=sys.stderr)
        return 1
    except Exception:
        # Never dump arbitrary DSN attributes or native driver diagnostics.
        print("Unexpected ODBC setup failure. Inspect the User DSN before retrying.", file=sys.stderr)
        return 1
