# Repository Agent Instructions

This repository contains the Altium component library, InvenTree integration tools and their specifications. Read the relevant documentation before changing code or library data. Keep changes focused, reuse established modules/names and do not redesign an architecture merely because another implementation is easier.

## Documentation hierarchy

| Responsibility | Authoritative document |
|---|---|
| Recommended categories, direct parameters and inheritance | [docs/inventree-category-structure.md](docs/inventree-category-structure.md) |
| IPN naming and engineering identity | [docs/ipn-naming-convention.md](docs/ipn-naming-convention.md) |
| Altium libraries, symbols, footprints and 3D conventions | [docs/library-convention.md](docs/library-convention.md) |
| Synchronization architecture and implementation contracts | [tools/inventree-sync/README.md](tools/inventree-sync/README.md) |
| Independent Windows ODBC setup contracts | [tools/setup-odbc/README.md](tools/setup-odbc/README.md) |
| End-user operation of both executables | [tools/README.md](tools/README.md) |

The linked technical contracts are mandatory; this file summarizes agent obligations without maintaining another full implementation specification. Markdown is for humans and agents, never a runtime source of component data unless explicitly required by the architecture. Recommended categories are not evidence of deployed server state.

When code and documentation disagree, investigate and report the affected files/behavior. Do not silently remove a requirement, invent source data or change architecture to justify a shortcut. Identify the conflict, explain the limitation and propose the smallest necessary change. Update externally visible documentation with behavior changes. Retain historical decisions only when they explain a current constraint; do not preserve obsolete development chronology as current requirements.

## Source of truth and scope

InvenTree is the sole source of component-library data. Retrieve categories/hierarchy, Parts/IPNs, actual Part parameters and referenced template metadata dynamically. InvenTree handles category assignment/inheritance; consume actual Part parameters instead of reconstructing inheritance locally.

Never maintain local configuration copies of the current category tree, category/inherited parameter lists, units, choices or leaf lists. Configuration describes synchronization rules and environment locations. Adding/removing/changing server data should be reflected without editing local category schemas.

Synchronization remains read-only and one-way:

```text
InvenTree -> PreparedDataset -> PreparedTables -> SQLite -> Altium DbLib
```

Do not add create/update/move/rename/delete API operations unless a future task explicitly changes this rule. Never synchronize generated database edits back to InvenTree. Never rewrite DbLib, SchLib or PcbLib during synchronization or ODBC setup. The tracked DbLib already uses DSN=AltiumComponents through MSDASQL; preserve its other bytes/settings unless explicitly authorized to edit it.

One Part produces one row; Stock Items, Supplier Parts and Manufacturer Parts do not create rows. Part.IPN is the identifier, with no fallback to Part.name. Do not regenerate/rename IPNs or derive Value, Package or electrical characteristics from IPN, name or description.

Do not silently repair source data: no category sanitizing, inferred libraries/footprints, arbitrary defaults, changed decimal separators/SI prefixes or numeric reinterpretation. Package is never an Altium footprint substitute. An error must identify the source object so it can be corrected there.

## Synchronization boundaries

Use Python 3.11+, program/console name `inventree-sync`, package `inventree_sync`, under `tools/inventree-sync/`. Follow the [module responsibilities](tools/inventree-sync/README.md#internal-boundaries). Keep HTTP/API-specific JSON in api/adapters; do not leak raw JSON unnecessarily into schema, transformation or writing.

`prepare_tables(dataset, layout)` is a separate database-independent API. It generates neither SQL nor files. `inspect` performs source retrieval checks; `validate` exercises the complete SQLite export in memory without output files/directories; default `sync` publishes a verified snapshot using sqlite.py. SQLite is the only backend. Use standard-library sqlite3, without ORM, backend selection or database credentials.

### Retrieval and schema

Follow the [API contract](tools/inventree-sync/README.md#inventree-api-and-authentication): InvenTree 1.5.6/API schema 530; fetch all accessible categories, resolve the configured root PK, then request Parts with category, cascade=true and parameters=true on every page. Never retrieve all Parts and discard those outside scope. Build shared indexes from nested actual parameters/template_detail. Missing/conflicting data fails; no fallback or separate parameter/template requests in this workflow.

Complete pagination; retain local tree/scope/Part validation after server filtering. Authorization/HTTP/malformed-pagination/unsupported-response failures must not become empty data. Determine supported behavior from the actual API contract, not guesses. Preserve authenticated redirect refusal and all transport/security checks.

Only populated exported leaves create tables; exact leaf names become table names. Empty leaves need no schema discovery. Enforce the naming grammar, sqlite_ reservation and case-insensitive table uniqueness in the technical reference; never rename or truncate identifiers.

For each leaf, derive columns from the union of actual Part parameter references. Validate all references before excluding exact names KiCad Symbol, KiCad Footprint, Altium Symbol and Altium Footprint. Retain all source parameters/templates in PreparedDataset. Resolve required Altium assignments independently of output columns; exclusions do not relax assignment, syntax, file-existence or exported model-name uniqueness checks.

Keep the six technical columns in order: IPN, Library Ref, Library Path, Footprint Ref, Footprint Path, InvenTree PK. Dynamic fields follow template PK order; tables category PK order; rows Part PK order. Missing optional assignments become None. InvenTree PK comes only from Part.pk as globally unique canonical positive decimal text; it is not the primary key or an extra index. An ordinary template with that name is a conflict.

### Text and transformation

Preserve original text in PreparedDataset. In PreparedTables, format ordinary values only with Parameter.data and ParameterTemplate.units, never data_numeric. Follow the [scalar/suffix rules](tools/inventree-sync/README.md#text-and-units) exactly: append missing units with one space, retain compatible existing suffixes including ohm/Ω/Ω, and reject conflicting/ambiguous values contextually. Do not format technical fields or excluded CAD parameters. Missing/empty values become None; whitespace-only optional values remain verbatim.

Keep strings such as 0603, 1%, 1E3 and =example textual. Do not emit placeholder strings None/NaN/NULL. Never return partial tables after validation failure.

Parse Altium Symbol/Footprint using the exact [reference grammar](docs/library-convention.md#accepted-reference-syntax); no trimming, library inference or Package fallback. Check configured library files and relative paths from DbLib. Do not claim binary model/pin/3D inspection. Do not synthesize Comment from Value; symbol Comment uses =Value. Explicit ordinary Comment parameters export normally.

### SQLite integrity and publication

Follow the complete [SQLite and publication contracts](tools/inventree-sync/README.md#sqlite-database), including direct writer validation of manually constructed PreparedTables. All columns TEXT; six technical columns NOT NULL; IPN PRIMARY KEY COLLATE NOCASE; global case-insensitive IPN and canonical InvenTree PK uniqueness; no auxiliary user tables/columns. Preserve prepared strings/NULL exactly.

Validate identifiers, quote with SQLite double quotes and escape embedded quotes. Parameterize values, never interpolate source values into SQL. Ordinary names may contain punctuation/Unicode but not leading whitespace/control characters; reject collisions. Engine limits fail explicitly, without truncation.

Build a complete unique staging snapshot in the destination directory, using a transaction, DELETE journaling and normal durable synchronization. Commit/close, reopen read-only, verify integrity, exact schema/constraints and every value, then close verification before os.replace. Failed synchronization before publication must preserve the old database.

Acquire exclusive `<destination>.sync.lock` before staging/publication; never steal/expire another process's lock. Recover stale locks only after manual confirmation that the owner and all relevant sync processes have stopped. Clean only owned staging/lock artifacts and check ownership. Report cleanup failures after publication accurately.

Under the lock, immediately before replacement, inspect destination -wal/-shm/-journal without opening the published database. Detect every entry, including empty files/dangling symlinks, and fail closed on inspection errors. Preserve external sidecars and destination; code 4 on publication failure. Never checkpoint/repair/delete external journals or force-close consumers. Let their owning application finish normal recovery/cleanup before retrying.

This lock coordinates sync processes only. Do not claim replacement protects all external readers/races. Close Altium/SQLite consumers before sync; continue reporting Windows sharing failures. Recovery must not recommend journal deletion to bypass protection.

## Configuration, credentials and deployment

The [configuration contract](tools/inventree-sync/README.md#configuration) is fixed: frozen config beside sys.executable; source config at repository tools/config.toml from module location. No public config override, cwd/parent/extraction search, first-run setup or automatic example reading/creation. Missing config fails clearly with the user-guide reference. Explicit internal path loading is for tests. Paths are TOML-relative; inspect needs only InvenTree/scope, validate/sync also require output/DbLib/library settings.

Reject output extensions other than .sqlite/.sqlite3, case-insensitively, and collisions with config/DbLib before retrieval/writes. Keep config.example.toml a tracked placeholder-only manual reference and local config untracked.

Default Basic Auth prompts once using input and secure getpass, passes HTTPBasicAuth explicitly and retains credentials only in memory. Abort if secure input is unavailable; no echoed fallback. Never use password arguments, TOML/.env credentials, Credential Manager or persisted tokens. Python cannot guarantee immediate string erasure. Legacy explicit token mode may read its configured environment variable; Basic needs none. HTTP and HTTPS work; keep normal TLS verification and redirect refusal. Do not log secrets or include them in exceptions, reports, fixtures or snapshots.

Use one ignored tools/inventree-sync/.venv for dev/tests/builds. Follow the [build contract](tools/inventree-sync/README.md#building-the-windows-executable): PSScriptRoot paths, Python 3.11+, test/build extras, full suite, unique build/ candidate from src/run.py, real executable smoke tests before same-volume atomic replacement of the single tracked tools/inventree-sync.exe. Failure preserves the old executable; clean only owned candidates. No launcher, permanent dist or archive. PyInstaller is build-only. Windows Python 3.11 CI uploads the final executable without committing.

Console ownership belongs to console.py/src/run.py. Explorer-owned interactive frozen consoles pause on Enter for success/help/errors, preserving exit codes and accounting for onefile parent/child processes. Existing terminals, redirected streams, CI and uncertain ownership must not pause. Test these policies on the actual built executable. No production credentials/server belong in tests.

## Independent Windows ODBC setup

Read and follow all contracts in [tools/setup-odbc/README.md](tools/setup-odbc/README.md) before changing this utility. It is a separate Python 3.11+ project/package setup_odbc with its own source, tests, .venv, build script, workflow and tracked Windows x64 console executable tools/setup-odbc.exe. Never import inventree_sync, share its environment/build, read TOML, contact InvenTree or launch PowerShell at runtime. Use standard-library ctypes/winreg; no external runtime dependency. Installed Python/PowerShell are not required by the executable.

Resolve only the existing ../database/components.sqlite from the executable/module layout, never cwd or a search. Never create/repair a database, edit Altium files, install/download drivers or directly write registry keys. Use documented Unicode Windows ODBC installer APIs; normal setup creates a 64-bit User DSN without elevation.

Keep DSN AltiumComponents fixed. Inspect host/64-bit SQLite3 ODBC Driver (sqlite3odbc.dll) and both registry views read-only. --driver-name selects only a compatible registered alias. List only SQLite driver names/platforms. Inspection errors fail closed. Reject orphaned registrations, System conflicts, incompatible DLL paths and 32-bit-only DSNs. Shared matching User views do not prove driver bitness. No Force override or modification of unrelated DSNs.

Create missing User DSNs via SQLConfigDataSourceW with NoCreat=1 and no GUI. Write Unicode Database via SQLWritePrivateProfileStringW with explicit User scope using SQLGetConfigMode/SQLSetConfigMode and restore prior mode. Existing compatible DSNs change only Database; equivalent paths remain unchanged. Reject non-text/expandable attributes before mutation and preserve other settings/types.

Validate SQLite header/length and reject every sidecar/inspection failure; hold CreateFileW read access without write/delete sharing throughout setup. Read back the complete expected DSN before connection verification. Use Unicode odbc32 APIs and read-only immutable URI plus NoCreat=1 because the driver ignores generic access-mode requests; immutable is valid only under the guarded journal-free snapshot assumption. Keep plain absolute paths in DSN storage. Execute only harmless fixed schema/database-list reads and verify the actual main file; close every resource. Suppress connection tracing and reject side-effect options and semicolon paths before mutation.

After failed mutation/verification, restore prior Database including absence, or remove a newly created DSN only with clear ownership. Compare full expected state before rollback and verify restoration. Preserve unexpected concurrent edits and report incomplete rollback alongside the original failure. A named same-session mutex coordinates this tool only; installer APIs are not atomic transactions against external editors.

Public CLI: default setup, --check-only, --driver-name, --help only; codes 0 verified, 1 setup/runtime failure, 2 argument error. --check-only never mutates DSNs. Build independently using unique onefile/console candidates, full tests and real executable checks before replacement; preserve old executable on failure and clean only owned artifacts. Apply the same Explorer/terminal/CI console guarantees. No launcher, permanent dist or ZIP.

Ordinary tests mock ODBC without an installed driver. Opt-in native integration uses disposable databases and uniquely named temporary User DSNs; clean only those resources. Never use production AltiumComponents or the tracked snapshot in tests. Altium placement/mapping checks remain manual. Runtime/CI never commit or push.

## Coding, errors and tests

Prefer standard-library functionality, dataclasses, explicit types, pathlib, logging and small deterministic functions. Avoid unnecessary frameworks, ORMs, dependencies, global mutable state, metaprogramming or trivial abstraction hierarchies.

Expected user/data/API failures must be clean and contextual: Part PK/IPN, category PK/path, template PK/name and affected paths where applicable. Follow documented exit codes. Do not hide validation behind generic Invalid data or expose credentials/raw responses. Normal unexpected-error output is concise; do not invent an undocumented debug mode.

Every behavior needs appropriate tests. Add regression coverage for bugs where practical; do not weaken/delete tests solely to pass changed code unless an explicitly changed requirement invalidates them. Unit tests use no production credentials/server, Altium or installed ODBC. Separate native integration explicitly. Fixtures must be minimal, anonymized and representative, covering pagination, missing values, empty leaves, differing parameter sets, bad references and API failures as applicable.

## Git and generated artifacts

Keep changes within the task. Never create commits, branches, tags, releases or PRs without explicit instructions; never rewrite Git history or force-push. Inspect the complete diff and remove accidental changes, temporary generated files and secrets before completion.

Three intentional tracked artifacts are database/components.sqlite, tools/inventree-sync.exe and tools/setup-odbc.exe. Preserve tracked status. Verify database integrity/schema/content and no journal dependencies before tracking an update; never fabricate a production substitute. Sync API failure reports an existing database unchanged/available offline while retaining its failure code. The snapshot never synchronizes back to InvenTree.

Respect .gitignore. Other SQLite files, staging/journals/locks, local config and environments normally remain ignored; maintained SQL fixtures remain trackable. Do not remove unrelated historical artifacts as cleanup.

## Before reporting completion

Re-read the task and relevant contracts. Check the full diff for scope, unintended artifacts/secrets and documentation consistency. Run relevant tests and any configured lint/format/type checks; report checks that could not run. Do not claim completion while required behavior is missing.

Provide a concise report of behavior, files created/modified, tests/results, assumptions, limitations and discrepancies. Distinguish unit verification from real Windows/ODBC/Altium integration; neither SQLite tests nor a single sample connection proves every production mapping.

Component-library data belongs in InvenTree. Synchronization behavior and conversion rules belong in the repository.
