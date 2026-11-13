# inventree-sync

One-way InvenTree → prepared Altium tables → SQLite snapshots. SQLite is the only supported database backend. Generation uses Python 3.11+ and its standard-library `sqlite3`; it does not require an ODBC driver. Altium consumes the result through the separately configured SQLite ODBC connection.

From the repository root in PowerShell:

```powershell
python -m venv tools/inventree-sync/.venv
& ./tools/inventree-sync/.venv/Scripts/python.exe -m pip install -e ./tools/inventree-sync
```

Copy [config.example.toml](config.example.toml) to local, ignored `config.toml` only if that file does not already exist. Set the server URL, category scope and runtime API-token environment variable. Existing inspection-only configurations need the new `[sync]` and `[libraries]` sections for validation/synchronization. Every filesystem path resolves relative to the TOML directory. `sync.output` and `sync.dblib` are independent; the DbLib file need not exist. No credentials belong in TOML or Git. The program does not load `.env` files itself.

For `validate` and `sync`, `sync.output` must end in `.sqlite` or `.sqlite3` (case-insensitive). Other extensions, including `.accdb`, `.db`, and extensionless paths, are configuration errors (exit code `2`) before retrieval or output writes. Output must also differ from the configuration and DbLib paths.

```powershell
& ./tools/inventree-sync/.venv/Scripts/inventree-sync.exe inspect --config ./tools/inventree-sync/config.toml
& ./tools/inventree-sync/.venv/Scripts/inventree-sync.exe validate --config ./tools/inventree-sync/config.toml
& ./tools/inventree-sync/.venv/Scripts/inventree-sync.exe sync --config ./tools/inventree-sync/config.toml
```

`inspect` preserves the read-only Milestone 1B behavior. `validate` checks the complete export, library-file existence and real SQLite schema/data in memory, without creating output files or directories. `sync` rebuilds the complete snapshot in a unique staging file, closes it, reopens it read-only, verifies integrity/schema/constraints/every value, then uses `os.replace` to publish it. All fields are `TEXT`; `IPN` is the non-null case-insensitive primary key, the other four technical fields are non-null, and optional parameters support SQL `NULL`. Unit formatting and CAD exclusions occur only during preparation.

Creation, insertion, commit, verification or replacement failures preserve the old published database. A `<destination>.sync.lock` coordinates only `inventree-sync` writers. Never delete a lock just because it is old: check its PID and confirm no sync to that destination is running before manually removing an abandoned lock. After a crash, remove only confirmed abandoned staging artifacts.

While holding that lock, immediately before replacement, the writer checks `<destination>-wal`, `-shm`, and `-journal` without opening the existing database. Any entry, including an empty file, directory or broken symlink, blocks publication; failure to inspect a path also blocks it. These sidecars can belong to active or interrupted transactions, so replacing only the main database would risk inconsistent state. The command reports the conflicting path with exit code `4`, preserves the destination and external sidecars, and cleans up its own staging file and lock. It never checkpoints, repairs or automatically deletes external journals.

Close Altium and other SQLite consumers before synchronization. The application lock and sidecar checks cannot detect every external reader or prevent a consumer from opening the database after the check; `os.replace` alone does not guarantee safety against arbitrary concurrent applications. Windows replacement-lock errors are still reported. If publication is blocked, close consumers normally and let SQLite complete its transactions and normal journal cleanup before retrying. If sidecars persist, use the owning application's normal SQLite recovery workflow; do not manually delete journals to bypass the check. The tool does not force-close processes.

Open the result in DB Browser for SQLite or SQLiteStudio to inspect tables and data. In Altium, point the previously tested SQLite ODBC connection at `sync.output`, select current component tables, use `IPN` as key and map the four technical model fields. The schematic symbol's Comment string `=Value` uses the ordinary `Value` parameter. The tool does not synthesize `Comment` or edit Altium libraries/DbLib. Verify placement and PCB footprint transfer manually; library-file checks do not inspect binary models.

Exit codes: `0` success, `1` unexpected error, `2` configuration/data, `3` API/authentication, `4` database/filesystem/locking/publication. Missing runtime credentials remain configuration errors (`2`).

Install test dependencies and run the complete offline suite:

```powershell
& ./tools/inventree-sync/.venv/Scripts/python.exe -m pip install -e './tools/inventree-sync[test]'
& ./tools/inventree-sync/.venv/Scripts/python.exe -m pytest tools/inventree-sync/tests
```

See the [architecture](../../docs/architecture/inventree-sync-design.md) for source contracts, configuration, unit-recognition limits, publication and recovery details. JSON audit reports and binary model indexing remain future work.
