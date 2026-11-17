# inventree-sync: developer guide

One-way InvenTree -> PreparedDataset -> PreparedTables -> verified SQLite snapshot -> Altium DbLib. Python 3.11+ and standard-library sqlite3 generate the database; ODBC is needed only by Altium. See the [architecture](../../docs/architecture/inventree-sync-design.md) for the complete contracts and [Ukrainian user guide](../README.md) for daily use.

## Layout and configuration

```text
database/components.sqlite           # tracked, verified offline snapshot
tools/
  inventree-sync.exe                 # tracked, verified Windows executable
  config.toml                        # local, ignored
  config.example.toml                # reference only
  README.md                          # user instructions
  inventree-sync/
    README.md
    pyproject.toml
    build.ps1
    .venv/                           # single development/test/build environment
    build/                           # ignored candidates and diagnostics
    src/
      run.py                         # frozen console entry point
      inventree_sync/
        __main__.py                  # python -m inventree_sync
        cli.py                       # orchestration, credentials, summaries
        console.py                   # Windows console ownership and final pause
        config.py                    # TOML and fixed external location
        api.py / adapters.py         # HTTP and supported API response shapes
        categories.py / retrieval.py # scoped source data, actual parameters
        models.py / schema.py        # typed models, dynamic schema union
        transform.py / validate.py   # Altium references, units, validation
        sqlite.py                    # schema, complete verification, publication
    tests/                           # fixtures, regressions, Windows smoke tests
```

Frozen execution reads only `Path(sys.executable).resolve().parent / "config.toml"`. Source execution resolves `tools/config.toml` from `config.py`'s location. Neither mode searches cwd, parents or the extraction directory. Missing configuration is an error. The reference example is never read by runtime discovery; users create their config manually. Public CLI arguments select only `sync` (default), `validate`, `inspect`, or help. Explicit-path `load_config()` remains an internal Python API for tests.

All configured paths resolve relative to the TOML directory. `[sync]` output/dblib and `[libraries]` symbols/footprints are required for validate/sync; inspect can use just inventree/scope. Output must use `.sqlite` or `.sqlite3`, differ from config/DbLib, and pass validation before retrieval.

## Development and tests

From the repository root, use the same environment for every step:

```powershell
python -m venv tools/inventree-sync/.venv
& ./tools/inventree-sync/.venv/Scripts/python.exe -m pip install -e './tools/inventree-sync[test,build]'
& ./tools/inventree-sync/.venv/Scripts/python.exe -m inventree_sync --help
& ./tools/inventree-sync/.venv/Scripts/python.exe -m pytest tools/inventree-sync/tests -p no:cacheprovider
```

Reuse an existing `.venv`; do not recreate it unnecessarily. Dependencies and extras are pinned in pyproject.toml. No formatter, linter or type-checker is currently configured. Tests use anonymized fixtures, mocked transport, temporary databases and local synthetic HTTP servers, never production credentials/server/Altium/ODBC.

Default Basic Auth prompts once for Username and hidden Password, explicitly propagating HTTPBasicAuth to retrieval. No credentials are persisted, and insecure echoed getpass fallback is rejected. HTTP and HTTPS remain supported, normal TLS verification is retained, and authenticated redirects are refused. Legacy token auth is opt-in through its configured environment variable. Python cannot guarantee immediate credential-string erasure. No credentials may enter logs or fixtures.

## Windows build and publication

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/inventree-sync/build.ps1
# Optional interpreter for initial environment creation:
powershell -NoProfile -ExecutionPolicy Bypass -File tools/inventree-sync/build.ps1 -Python 'C:\Python311\python.exe'
```

The script resolves paths from PSScriptRoot, creates/reuses `.venv`, verifies Python 3.11+, installs `[test,build]`, and runs the full suite. PyInstaller (build-only) builds `src/run.py` with `--onefile --console` into a unique `build/candidate-*` directory. Real executable smoke tests must pass before `os.replace` publishes `tools/inventree-sync.exe`. Test, dependency, packaging, smoke or replacement failures preserve the previous executable. A running executable may block replacement on Windows: close it normally and rebuild. Only this build's candidate directory is cleaned up.

No distribution subdirectory, archive or launcher is needed. Runtime Python and dependencies are bundled. Source, tests and external configuration/libraries stay outside the executable. To test a separately built candidate without publishing it:

```powershell
& ./tools/inventree-sync/.venv/Scripts/python.exe -m pytest tools/inventree-sync/tests/test_packaging.py --sync-executable 'C:\Candidate folder\inventree-sync.exe' -p no:cacheprovider
```

Smoke tests use paths containing spaces and a runtime PATH with no Python. They exercise real hidden getpass, strict configuration location, redirected execution, Explorer-style console ownership, PowerShell launch, CI behavior, success/error exit codes and a synthetic full SQLite sync. PowerShell orchestration fault-injection tests cover new/reused environments and each failure gate; these are distinct from real PyInstaller compilation.

The executable pauses with `Press Enter to close this window...` only when it owns an interactive Windows console. [GetConsoleProcessList](https://learn.microsoft.com/en-us/windows/console/getconsoleprocesslist) identifies attached processes; the onefile parent is allowed only when its image matches the application's executable. Existing terminals, redirected streams, CI and uncertain detection do not pause. Help and argparse errors use the same finalizer. Source/module execution never pauses.

The Windows GitHub Actions workflow uses Python 3.11, runs this script and uploads `tools/inventree-sync.exe` directly as the workflow artifact. It never commits binaries. The previous failed run [43474057233](https://github.com/dm-serhieiev/altium-library/actions/runs/43474057233) had 29 failures caused by the missing committed configuration example; the new tracked example and path tests address that cause without weakening retrieval checks.

## SQLite and tracked snapshot policy

InvenTree remains the source of truth. Only nonempty exported leaf categories become tables, named exactly as in InvenTree. Actual Part parameters drive schemas. Six technical TEXT columns are followed by dynamic columns in template PK order. IPN is the case-insensitive primary key; generated InvenTree PK is globally unique canonical decimal text. CAD source parameters are excluded after validation. Ordinary values preserve textual data with the specified unit formatting. No synthetic Comment is created; the schematic symbol uses `=Value`.

`inspect` reads source data; `validate` exercises the full export in memory. Neither changes the database. Sync writes a complete transaction in a unique staging file, closes it, reopens read-only, verifies integrity/schema/constraints/every value, and closes verification before replacement. It holds an exclusive destination lock and checks all WAL/SHM/journal entries immediately before publication. Existing sidecars or inspection errors block publication. Never delete external journals, force-close consumers, checkpoint/repair their database, or assume os.replace protects arbitrary concurrent readers. Close Altium/viewers before sync. Recover an abandoned sync lock manually only after confirming its owner and all sync processes are stopped.

API/authentication, validation, staging, verification and publication failures preserve the previous database. A sync API failure explicitly reports an existing local snapshot as unchanged and available offline, while returning failure. `database/components.sqlite` is an intentional tracked cache, not a second source of truth. Before manually committing an updated snapshot, close consumers, verify integrity/schema/content and ensure no journal dependencies remain. Other generated databases, sidecars, locks, candidates, environment files and local config remain ignored. The verified `tools/inventree-sync.exe` is also intentionally tracked. No runtime/build step commits or pushes either artifact.

Altium DbLib and binary symbol/footprint libraries are never modified by synchronization. The independent [setup-odbc project](../setup-odbc/README.md) produces `tools/setup-odbc.exe`, which configures the local 64-bit `AltiumComponents` User DSN. The tracked DbLib uses that stable DSN through MSDASQL. Setup resolves the standard `database/components.sqlite` path independently of synchronization TOML and has its own package, environment, tests, build and workflow. The inventree-sync test suite has no ODBC dependency.

See the [user guide](../README.md) for setup and verification. Configure field mappings manually, including ordinary `InvenTree PK` -> `InvenTree PK`. Unit tests and native executable tests do not prove Altium compatibility or the existence of models inside binary libraries. Verify lookup, placement, `Comment =Value`, parameters and PCB footprint transfer manually.

Exit codes: 0 success; 1 unexpected error; 2 configuration/data/secure input; 3 API/authentication; 4 database/filesystem/locking/publication.
