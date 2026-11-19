# setup-odbc: developer guide

This independent Python 3.11+ project configures the local Windows x64 `AltiumComponents` User DSN for Altium DbLib. The shipped `../setup-odbc.exe` needs neither Python nor PowerShell. It reads no TOML, imports no `inventree_sync` code, contacts no server and never changes SQLite or Altium files. Its environment, tests, executable and CI build are separate from synchronization.

This is the authoritative ODBC implementation reference. See the [end-user guide](../README.md) for normal operation and the [synchronization reference](../inventree-sync/README.md#altium-integration) for snapshot generation and manual DbLib mappings. Setup always targets `database/components.sqlite`; changing synchronization output in TOML does not change this path.

## Command-line interface

From the repository root:

```powershell
.\tools\setup-odbc.exe
.\tools\setup-odbc.exe --check-only
.\tools\setup-odbc.exe --driver-name 'SQLite3 ODBC Driver'
.\tools\setup-odbc.exe --help
```

The DSN is fixed as `AltiumComponents`. `--driver-name` accepts only a compatible installed alias; it does not install a driver. `--check-only` verifies existing state without changing it. No Force override, arbitrary database path or DSN-name argument is public. Exit codes are `0` verified, `1` setup/runtime failure and `2` argument error.

## Layout

```text
tools/
├── setup-odbc.exe              # verified, intentionally tracked
└── setup-odbc/
    ├── README.md
    ├── pyproject.toml
    ├── build.ps1
    ├── .venv/                 # ignored; dev, tests and builds
    ├── build/                 # ignored; unique candidates only
    ├── src/run.py             # frozen console entry point
    ├── src/setup_odbc/
    │   ├── __init__.py
    │   ├── __main__.py
    │   ├── cli.py             # fixed DSN, arguments and summaries
    │   ├── console.py         # Explorer ownership and final Enter prompt
    │   ├── database.py        # executable/source-relative path and read guard
    │   ├── drivers.py         # read-only registration inspection
    │   ├── dsn.py             # installer APIs, conflicts and rollback
    │   ├── odbc.py            # Unicode ODBC connection and fixed read queries
    │   └── errors.py
    └── tests/                 # mocks, packaging and opt-in native integration
```

Runtime dependencies: Python standard library only (`ctypes`, `winreg`, `pathlib`, `argparse` and supporting modules). `setuptools` builds the package; `pytest` is the test extra and `PyInstaller` the build extra. No `pyodbc`, `pywin32`, driver download or subprocess-based setup is used. PyInstaller's own build dependencies are not application runtime dependencies.

## Development and builds

From the repository root, using Windows x64 and 64-bit Python 3.11+:

```powershell
python -m venv tools/setup-odbc/.venv
.\tools\setup-odbc\.venv\Scripts\python.exe -m pip install -e './tools/setup-odbc[test,build]'
.\tools\setup-odbc\.venv\Scripts\python.exe -m setup_odbc --help
.\tools\setup-odbc\.venv\Scripts\python.exe -m pytest tools/setup-odbc/tests -p no:cacheprovider
.\tools\setup-odbc\build.ps1
```

If local PowerShell execution policy blocks developer scripts, use a process-only override:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\setup-odbc\build.ps1
```

`build.ps1 -Python <python.exe>` selects the interpreter for initial environment creation. It always uses its own `.venv`, checks 64-bit Python 3.11+, installs the extras, runs the unit suite, builds a unique candidate using `--onefile --console --name setup-odbc` and `src/run.py`, and runs the real executable tests. Only then does `os.replace` publish `tools/setup-odbc.exe`. Failures leave an existing executable intact. Close running setup instances if publication is blocked. Cleanup owns only that build's candidate directory; no permanent `dist`, ZIP or launcher is created.

`.github/workflows/setup-odbc-windows.yml` does the same on `windows-latest` with Python 3.11 x64 and uploads the executable directly. It neither commits nor pushes. ODBC source changes do not trigger the synchronization workflow.

## Native Windows contract

Frozen execution resolves `Path(sys.executable).resolve().parent / '../database/components.sqlite'`; source execution resolves the same repository layout from the module. Cwd and `config.toml` are irrelevant. A `CreateFileW` read handle with only `FILE_SHARE_READ` is held throughout setup. The header, page size and file length must be plausible; all WAL/SHM/journal entries and inspection errors block setup. No creation, repair, checkpoint, journal deletion or table changes are permitted.

`winreg` reads registrations in both 32-bit and 64-bit views. Only the installed SQLite3 x64 registration whose DLL is `sqlite3odbc.dll` is supported; `--driver-name` permits an explicit compatible alias. Same-name System DSNs, orphaned registrations, another driver/DLL, mismatched views and nonempty `TraceFile`, `LoadExt`, `AttachAs`, `JournalMode` or `SyncPragma` are conflicts. A matching shared User DSN view is allowed. Semicolons in repository paths remain rejected because of the driver's setup parser limitation.

`SQLConfigDataSourceW` (`odbccp32.dll`) creates/removes only a User DSN, with a null GUI handle and a double-null-terminated attribute buffer. Creation first writes the ASCII `DSN` and `NoCreat=1` attributes. `SQLWritePrivateProfileStringW`, scoped by `SQLGetConfigMode`/`SQLSetConfigMode`, writes the Unicode `Database` path without relying on the driver's ANSI setup parser. Updates write only `Database`; rollback can restore its original absence with a null value. Equivalent absolute paths are left unchanged, including other DSN settings.

DSN settings must be ordinary registry strings. Non-text and expandable values are rejected before mutation so rollback cannot silently change their original type or expansion semantics. Numeric driver metadata such as UsageCount is unrelated and allowed.

Configuration is read back before testing. `odbc32.dll` uses `SQLAllocHandle`, `SQLSetEnvAttr`, `SQLSetConnectAttrW`, `SQLDriverConnectW` (no prompt), `SQLExecDirectW`, `SQLFetch`, `SQLGetData`, `SQLGetDiagRecW`, `SQLDisconnect` and `SQLFreeHandle`. Pointer-sized handles and SQLLEN, Unicode strings, buffer sizes and handle cleanup are explicit. Diagnostics expose SQLSTATE, not private DSN values or driver message text. Connection tracing is disabled for verification.

The driver ignores generic `SQL_ATTR_ACCESS_MODE`. Verification instead overrides the already checked plain DSN path with its equivalent SQLite URI `mode=ro&immutable=1`, plus `NoCreat=1`. The immutable assumption applies only to the guarded snapshot without journals. Only `SELECT name FROM sqlite_master LIMIT 1` and `PRAGMA database_list` execute in production; the latter confirms the actual main file. The stored DSN retains a plain absolute path.

On configuration or connection failure, read-back establishes whether rollback is safe. Existing settings must match either the original or this operation's expected state; unexpected concurrent changes are preserved and reported as incomplete rollback. A new DSN is removed only when its complete expected state is recognized. Previous database attribute values, including absence, are restored and read back. A named Windows mutex serializes this tool's instances in the same session. ODBC configuration is not a transaction or an atomic compare-and-swap with other programs: do not edit the same DSN in ODBC Administrator during setup. Interrupted or ambiguous partial states require manual inspection. No unrelated DSN is modified.

Explorer-owned frozen consoles wait for Enter on success, errors and help. Ownership detection accounts for both PyInstaller processes. Existing terminals, redirected streams, CI and pytest do not pause; uncertain detection never blocks automation. CLI exit codes: `0` verified, `1` setup/runtime failure, `2` argument error. `--check-only` never creates, updates or removes DSNs.

Primary API references: [ODBC installer configuration](https://learn.microsoft.com/en-us/sql/odbc/reference/syntax/sqlconfigdatasource-function), [profile attribute writes](https://learn.microsoft.com/en-us/sql/odbc/reference/syntax/sqlwriteprivateprofilestring-function), [installer scope](https://learn.microsoft.com/en-us/sql/odbc/reference/syntax/sqlsetconfigmode-function), [shared User DSN views](https://learn.microsoft.com/en-us/troubleshoot/sql/connect/odbc-tool-displays-32-bit-64-bit), [SQLite URI semantics](https://sqlite.org/uri.html).

## Verification

Ordinary tests block native ODBC DLL loading and mock configuration/connection operations. Tests cover failures before and after mutation, complete rollback and concurrent edits, missing previous attributes, Unicode paths, sidecars and sharing guards, DSN conflicts, native signatures/resource cleanup, and build failures preserving the published executable. Packaging tests remove Python from runtime PATH, use unrelated cwd and disposable layouts, and test hidden real Windows consoles for Explorer-style, terminal and CI launching. They never configure `AltiumComponents`.

Optional installed-driver integration:

```powershell
.\tools\setup-odbc\.venv\Scripts\python.exe -m pytest tools/setup-odbc/tests --odbc-integration -p no:cacheprovider
```

This uses disposable databases and a unique `AltiumTest-...` User DSN, including create/repeat/move/check, corrupt-schema rollback, restoration of attribute absence, rejected writes even without the file guard, and no-create behavior. It checks unchanged database bytes and cleans only its own DSN. Missing driver means an explicit skip. Neither the production DSN nor the tracked snapshot is changed. Running executable smoke tests independently uses `--setup-executable <absolute-exe-path>`.

Altium **Connect**, IPN lookup, mappings, symbol placement and footprint transfer remain manual checks; ODBC tests cannot establish them.
