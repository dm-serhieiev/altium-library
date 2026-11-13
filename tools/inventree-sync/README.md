# inventree-sync

One-way InvenTree → prepared Altium tables → SQLite snapshots. SQLite is the only supported database backend. Generation uses Python 3.11+ and its standard-library `sqlite3`; it does not require an ODBC driver. Altium consumes the result through the separately configured SQLite ODBC connection.

Download the `inventree-sync-windows` workflow artifact, extract its ZIP over the repository root, then run from PowerShell:

```powershell
.\sync
.\sync validate
.\sync inspect
.\sync --help
```

The launcher locates `tools/inventree-sync/dist/inventree-sync.exe` relative to itself, forwards arguments and preserves exit codes. It does not install anything or change the user's environment. Its stock Windows PowerShell helper keeps an Explorer double-click console open after completion; terminal and redirected invocations do not pause. No external Python installation or administrator privileges are needed to use the executable.

With no command, the default is `sync`. `--config` is optional and works with any command, for example `.\sync validate --config "C:\Library Settings\config.toml"`. Without it, configuration is found at `tools/inventree-sync/config.toml` relative to the source application or external executable/repository, never the current directory or PyInstaller extraction directory. A standalone executable outside the repository can use external config/example files beside itself.

If the default config is missing, first-run setup asks for the server URL and root category (default `Electronic Components`), preserves the filesystem paths from [config.example.toml](config.example.toml), and exclusively creates local `config.toml`. Existing files are never rewritten. An explicit missing `--config` is an error, not a first-run setup request. All paths still resolve relative to the TOML directory; output and DbLib paths are independent, and the DbLib need not exist. Advanced users can edit all paths manually. Old inspection-only configs need `[sync]` and `[libraries]` for full export.

New configs use `auth = "basic"` (also the default when omitted). Each command prompts once with `input()` for Username and `getpass()` for a hidden Password, then passes the same `HTTPBasicAuth` object explicitly to every read-only request. Credentials exist only in the running process: no `.env`, TOML, token creation, Credential Manager or password arguments. Python does not guarantee immediate erasure of strings from memory. If hidden input is unavailable, execution fails instead of falling back to echoed password entry.

Both HTTP and HTTPS are supported, including local HTTP; HTTPS retains normal certificate verification and authenticated redirects are not followed. Basic Auth does not encrypt credentials over HTTP. Server policies such as MFA/SSO can refuse Basic Auth; the program reports authentication/permission errors without printing response bodies or Authorization headers. It cannot always distinguish a wrong password from a server policy rejection on HTTP 401. Requests HTTPBasicAuth uses Latin-1 credential encoding; unsupported characters fail clearly without echoing them. See [InvenTree authentication](https://docs.inventree.org/en/stable/api/#authentication).

Legacy `auth = "token"` remains opt-in, using `token_env` (default `INVENTREE_API_TOKEN`). Existing token configs are preserved; change their `auth` manually to `basic` to use interactive login. Basic mode never requires a token. The program does not load `.env` itself.

For `validate` and `sync`, `sync.output` must end in `.sqlite` or `.sqlite3` (case-insensitive). Other extensions, including `.accdb`, `.db`, and extensionless paths, are configuration errors (exit code `2`) before retrieval or output writes. Output must also differ from the configuration and DbLib paths.

```powershell
# Optional developer workflow (Python 3.11+):
python -m venv tools/inventree-sync/.venv
& ./tools/inventree-sync/.venv/Scripts/python.exe -m pip install -e ./tools/inventree-sync
& ./tools/inventree-sync/.venv/Scripts/python.exe -m inventree_sync
```

`inspect` preserves read-only source inspection. `validate` checks the complete export, library-file existence and real SQLite schema/data in memory without creating database output files/directories. First-run setup can create the credential-free configuration before any command. `sync` rebuilds the complete snapshot in a unique staging file, closes it, reopens it read-only, verifies integrity/schema/constraints/every value, then uses `os.replace` to publish it. Progress messages report completed phases only after they succeed. All fields are `TEXT`; `IPN` remains the non-null case-insensitive primary key. The six technical columns are `IPN`, `Library Ref`, `Library Path`, `Footprint Ref`, `Footprint Path`, `InvenTree PK`. Optional parameters support SQL `NULL`. Unit formatting and CAD exclusions occur only during preparation.

Creation, insertion, commit, verification or replacement failures preserve the old published database. A `<destination>.sync.lock` coordinates only `inventree-sync` writers. Never delete a lock just because it is old: check its PID and confirm no sync to that destination is running before manually removing an abandoned lock. After a crash, remove only confirmed abandoned staging artifacts.

While holding that lock, immediately before replacement, the writer checks `<destination>-wal`, `-shm`, and `-journal` without opening the existing database. Any entry, including an empty file, directory or broken symlink, blocks publication; failure to inspect a path also blocks it. These sidecars can belong to active or interrupted transactions, so replacing only the main database would risk inconsistent state. The command reports the conflicting path with exit code `4`, preserves the destination and external sidecars, and cleans up its own staging file and lock. It never checkpoints, repairs or automatically deletes external journals.

Close Altium and other SQLite consumers before synchronization. The application lock and sidecar checks cannot detect every external reader or prevent a consumer from opening the database after the check; `os.replace` alone does not guarantee safety against arbitrary concurrent applications. Windows replacement-lock errors are still reported. If publication is blocked, close consumers normally and let SQLite complete its transactions and normal journal cleanup before retrying. If sidecars persist, use the owning application's normal SQLite recovery workflow; do not manually delete journals to bypass the check. The tool does not force-close processes.

Open the result in DB Browser for SQLite or SQLiteStudio to inspect tables and data. In Altium, point the previously tested SQLite ODBC connection at `sync.output`, select current component tables, use `IPN` as key and map the four technical model fields. The schematic symbol's Comment string `=Value` uses the ordinary `Value` parameter. The tool does not synthesize `Comment` or edit Altium libraries/DbLib. Verify placement and PCB footprint transfer manually; library-file checks do not inspect binary models.

In Altium DbLib Field Mapping, manually add Database Field Name `InvenTree PK` → Design Parameter `InvenTree PK`, with exactly that spelling and no brackets. This is an ordinary design parameter. It comes directly from `Part.pk` as positive canonical decimal text (`1257` → `"1257"`), is mandatory and globally unique across tables, and has no additional SQLite index. A ParameterTemplate with the same name is a column conflict. IPN remains the database key; existing schematic components are not updated automatically. Place a new component to verify the parameter alongside the existing `Comment =Value` mechanism.

Exit codes: `0` success, `1` unexpected error, `2` configuration/data, `3` API/authentication, `4` database/filesystem/locking/publication. Missing runtime credentials remain configuration errors (`2`).

Install test dependencies and run the complete offline suite:

```powershell
& ./tools/inventree-sync/.venv/Scripts/python.exe -m pip install -e './tools/inventree-sync[test]'
& ./tools/inventree-sync/.venv/Scripts/python.exe -m pytest tools/inventree-sync/tests
```

See the [architecture](../../docs/architecture/inventree-sync-design.md) for source contracts, configuration, unit-recognition limits, publication and recovery details. JSON audit reports and binary model indexing remain future work.

Build the one-file console executable on Windows using Python 3.11+:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/inventree-sync/build.ps1
```

The script creates ignored `.venv-build`, installs test/build extras, runs offline tests, builds `dist/inventree-sync.exe`, and runs Windows smoke tests with Python absent from the executable's runtime PATH. Those tests include real hidden-console `getpass` input against a local synthetic HTTP server, external configuration, and launcher exit codes. It creates `dist/inventree-sync-windows.zip` as a repository overlay containing the executable, launcher/helper and external example; local config, credentials and libraries are excluded. PyInstaller is a build-only dependency. The GitHub Actions Windows workflow runs this script and uploads the ZIP; no executable is committed. Packaging uses `sys.executable` to locate the external frozen application, as described in [PyInstaller runtime information](https://pyinstaller.org/en/stable/runtime-information.html#using-sys-executable-and-sys-argv-0).
