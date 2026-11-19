# inventree-sync

This is the authoritative technical reference for synchronization. See the [Windows user guide](../README.md), [category convention](../../docs/inventree-category-structure.md), [IPN convention](../../docs/ipn-naming-convention.md) and [Altium library convention](../../docs/library-convention.md). Windows ODBC configuration has a separate [setup-odbc reference](../setup-odbc/README.md).

## Overview and architecture

InvenTree is the single source of truth. Synchronization is strictly one-way:

```text
InvenTree REST API
    -> PreparedDataset (validated source records and indexes)
    -> PreparedTables (immutable, database-independent logical tables)
    -> verified SQLite snapshot
    -> Altium DbLib through SQLite ODBC
```

One Part becomes one row. One populated leaf category becomes one table, named exactly after that category. Stock Items, Manufacturer Parts and Supplier Parts do not create additional rows. SQLite is the only backend; generation uses standard-library `sqlite3`.

The application never writes to InvenTree or edits Altium/3D files. It does not parse Markdown as component data, reconstruct category inheritance, derive parameters from IPNs or preserve manual database edits. Each successful synchronization publishes a complete replacement snapshot.

### Internal boundaries

| Module | Responsibility |
|---|---|
| `cli.py` | Arguments, command orchestration, secure input and exit codes |
| `console.py`, `src/run.py` | Frozen Windows console ownership and final pause |
| `config.py` | Fixed configuration location, validation and path resolution |
| `api.py` | Read-only HTTP, authentication, pagination, redirects and retries |
| `adapters.py` | API-specific JSON validation and conversion to internal records |
| `models.py` | Frozen category, Part, parameter, template, schema and table records |
| `categories.py` | Category tree, scope, leaf groups and table-name validation |
| `retrieval.py` | Scoped retrieval and construction of PreparedDataset |
| `schema.py` | Dynamic column discovery from actual Part parameters |
| `transform.py` | Model references, paths and textual unit formatting |
| `validate.py` | Logical export, identifier, row and model-conflict checks |
| `sqlite.py` | In-memory validation, snapshot writing, verification and publication |

Raw API JSON stays in the HTTP/adapter boundary. `prepare_tables(dataset, layout)` remains a separate Python API: no HTTP, SQL, output directories or database writes. Its only filesystem work checks referenced library files. It returns complete prepared tables or raises a contextual error.

`PreparedDataset` contains the category tree, root PK, scope PKs, Parts indexed by PK, parameters indexed by Part PK and template PK, referenced templates indexed by PK, and leaf-category groups. Frozen records/read-only mappings retain original source text. `PreparedTables` contains immutable schemas and rows, without a database connection.

The logical records are `ColumnDefinition(name, template_pk)`, `TableSchema(category_pk, name, category_path, columns)`, `PreparedTable(category_pk, name, category_path, columns, rows)` and `PreparedTables(tables)`. A technical column has `template_pk=None`; a dynamic column has its positive template PK. Collections are tuples; prepared rows are read-only mappings of `str` to `str | None`.

Public pipeline entry points are `retrieve_dataset(config_path, auth=None)` (accepting a path or Config object), `build_table_schemas(dataset)`, `prepare_tables(dataset, layout)`, `validate_sqlite_tables(prepared)` and `write_sqlite_database(prepared, destination)`. Basic-mode Python callers must supply the runtime `HTTPBasicAuth`; retrieval does not prompt for it. `ExportValidationError` is the logical validation base, with `SchemaError` and `ModelReferenceError` specializations; publication failures use `DatabaseError`. No stage returns a partial result after failure.

## Project structure and development environment

```text
tools/
├── config.example.toml         # tracked manual reference
├── config.toml                 # ignored local configuration
├── inventree-sync.exe          # tracked verified executable
└── inventree-sync/
    ├── README.md
    ├── pyproject.toml
    ├── build.ps1
    ├── .venv/                  # ignored; dev, tests and builds
    ├── build/                  # ignored; unique candidates
    ├── src/run.py
    ├── src/inventree_sync/
    └── tests/
```

Use Python 3.11+. Runtime HTTP uses requests; dependency versions and test/build extras are defined in [pyproject.toml](pyproject.toml). PyInstaller is build-only. From the repository root:

```powershell
python -m venv tools/inventree-sync/.venv
.\tools\inventree-sync\.venv\Scripts\python.exe -m pip install -e './tools/inventree-sync[test,build]'
.\tools\inventree-sync\.venv\Scripts\python.exe -m inventree_sync --help
.\tools\inventree-sync\.venv\Scripts\python.exe -m pytest tools/inventree-sync/tests -p no:cacheprovider
```

Reuse this environment for development, tests and builds. The ODBC utility has its own package, environment and build; neither project imports the other.

## Configuration

Frozen execution reads only `Path(sys.executable).resolve().parent / 'config.toml'`. Source execution resolves repository `tools/config.toml` from the module location. Neither mode searches cwd, parent directories, PyInstaller extraction or the example file. There is no public configuration-path argument. Internal explicit-path loading remains available for tests.

A missing file fails with code `2` and points to the [user guide](../README.md). Runtime never generates or edits configuration. Copy [config.example.toml](../config.example.toml) manually and customize it without overwriting an existing local file:

```toml
[inventree]
base_url = "https://inventree.example.com"
auth = "basic"
connect_timeout = 10
read_timeout = 60
retries = 3

[scope]
root_category_path = ["Electronic Components"]

[sync]
output = "../database/components.sqlite"
dblib = "../database/Components.DbLib"

[libraries]
symbols = "../symbols"
footprints = "../footprints"
```

All relative filesystem paths are relative to the TOML directory; absolute paths are accepted. `sync.dblib` anchors model paths and need not exist yet. Configuration contains no copied category schemas, units, choices, current leaf lists or component data. Unknown settings/sections are errors.

`inspect` needs only the InvenTree and scope sections. `validate` and `sync` also require every sync/library field. Output must end in `.sqlite` or `.sqlite3`, case-insensitively. Other extensions and paths overwriting configuration or DbLib fail before authentication, retrieval or writes. There is no backend selector or active/template/virtual Part filter.

Keep local configuration untracked and credential-free. Explicit legacy `auth = "token"` reads the environment variable named by `token_env` (default `INVENTREE_API_TOKEN`). Basic mode needs neither a token nor an environment variable.

Use the server URL without the appended `/api/`; deployment subpaths are supported. Embedded credentials, query strings and fragments are forbidden. Timeouts are finite positive seconds; retries is a non-negative integer (defaults shown above). Scope is a nonempty array of nonblank exact category-name segments. No all-database scope syntax exists.

## Command-line interface

```powershell
.\tools\inventree-sync.exe
.\tools\inventree-sync.exe sync
.\tools\inventree-sync.exe inspect
.\tools\inventree-sync.exe validate
.\tools\inventree-sync.exe --help
```

| Command | Work performed | Output effects |
|---|---|---|
| Default / `sync` | Retrieve, prepare, validate, generate, verify and publish | Replace configured SQLite on success |
| `inspect` | Retrieve and validate source structure/scope, then summarize | No SQLite output; not complete export validation |
| `validate` | Retrieve, prepare and exercise the full SQLite export in memory | No output file, directory or destination lock |

Validation checks the actual SQLite engine's schema/size limits, not only Python rows. Commands prompt once in Basic mode. Help needs no configuration or authentication.

## InvenTree API and authentication

The primary retrieval contract targets **InvenTree 1.5.6 / API schema 530**. It requires nested Part parameters/template metadata; it does not negotiate versions or probe alternative endpoints. Upstream definitions: [Part API](https://github.com/inventree/InvenTree/blob/1.5.6/src/backend/InvenTree/part/api.py), [Part serializers](https://github.com/inventree/InvenTree/blob/1.5.6/src/backend/InvenTree/part/serializers.py), [common serializers](https://github.com/inventree/InvenTree/blob/1.5.6/src/backend/InvenTree/common/serializers.py).

### Authentication and transport

Default authentication prompts with `input()` and secure `getpass()`, then passes `HTTPBasicAuth` explicitly through retrieval to the client. Reject a blank username, an empty password, a username containing a colon, credentials outside Requests' Latin-1 encoding, EOF and unavailable secure input. Echoed-password fallback is forbidden.

Credentials remain in runtime memory: no password arguments, TOML credentials, .env, Credential Manager, persisted tokens or credential logs. Python cannot guarantee immediate string erasure. Legacy token mode is explicit and never replaces Basic automatically.

Both HTTP and HTTPS work. Basic over HTTP is unencrypted; HTTPS retains normal certificate verification. Authenticated redirects are refused. The client disables implicit environment/netrc authentication and environment proxy/TLS overrides, clears cookies, closes responses and closes its session. Errors must not expose Authorization headers, credentials, response bodies or redirect secrets.

### Requests, pagination and failures

1. Fetch all accessible categories from `/api/part/category/`, including every page.
2. Resolve the exact configured full category path to one root PK.
3. Fetch `/api/part/` with `category=<root_pk>&cascade=true&parameters=true` on **every page**.

Do not download all Parts and discard those outside scope. No separate parameter/template calls, per-Part requests or automatic fallback belong in this workflow. Low-level diagnostic/unfiltered iterators are not the synchronization strategy. Normal request count is category pages plus scoped Part pages, excluding retries.

Accept unpaginated arrays or paginated `results`/`next` responses with optional count. Follow all pages; reject malformed structures, duplicate records, repeated/cyclic URLs, inconsistent counts and empty intermediate pages. Next-page URLs must retain the API origin and endpoint. All three Part filters must occur exactly once with unchanged values. Query reordering cannot bypass cycle checks.

Retry HTTP `429`, `500`, `502`, `503`, `504` up to the configured retries after the initial attempt. Respect valid Retry-After seconds/dates with a 60-second maximum; excessive delays fail. Otherwise use bounded exponential backoff. Connection/TLS/timeouts and 401/403 fail immediately. Authentication, permission, HTTP, pagination and unsupported response errors never mean an empty dataset.

## Data retrieval and source validation

Adapters produce typed records. Every Part must contain a parameters list (empty is structurally valid). Each actual parameter needs positive integer identifiers, a matching Part model_id, a template reference and nested template_detail with matching PK, textual name and units. If model_type is supplied, it must be part.part. Booleans are not integer identifiers.

Build shared indexes from nested data. Duplicate parameter PKs, duplicate template assignments on a Part, conflicting name/units for one template PK, missing nested metadata or inconsistent references fail. Choice/default/category-assignment metadata does not define the schema.

Use textual `Parameter.data`, never data_numeric. Null and empty string become Python None; all other text, including whitespace-only text, remains intact. Numeric JSON parameter values are not silently stringified. PreparedDataset retains this source representation.

The complete accessible category tree must have unique PKs, valid parents and no cycles. Resolve scope by exact full path. Determine leaves from the whole accessible tree. Every returned Part must have a known in-scope category, belong directly to a leaf and have a nonblank IPN. Server filtering does not replace these checks. Part PKs and case-insensitive IPNs must be globally unique. An export with no Parts fails.

InvenTree applies category parameters and inheritance to concrete Parts. Consume their actual assignments; never reconstruct inheritance locally. Permissions can hide categories/children, and paginated reads are not a transactional server snapshot.

## Category and schema processing

Only populated exported leaves produce tables. Empty leaves need no schema discovery. Table names preserve exact leaf names without path prefixes, sanitization, renaming or truncation, and must fully match:

```regex
[A-Za-z][A-Za-z0-9]*(?: [A-Za-z0-9]+)*
```

Names must be unique under casefold across exported branches. The SQLite sqlite_ prefix is reserved (underscores also fail the regex). There is no separate 64-character limit or reserved-word blacklist: a name such as Select is safely quoted. Engine limits still apply. Invalid names on non-exported empty categories do not create table-name errors.

For each populated leaf, union templates referenced by its actual Part parameters. Validate all references **before** excluding these exact names:

```text
KiCad Symbol
KiCad Footprint
Altium Symbol
Altium Footprint
```

Retain all source parameters/templates in PreparedDataset. KiCad values are ignored by Altium transformation. Altium parameters are mandatory source-only inputs, resolved independently of exported columns.

Validate key/object PK agreement and each parameter's ownership/reference even for excluded CAD parameters. Export requires Part.IPN, positive Part.pk and both Altium assignments; it does not reimplement InvenTree's required/default logic for ordinary category parameters.

| Technical column, in order | Source |
|---|---|
| IPN | Part.IPN, unchanged |
| Library Ref | Parsed symbol name |
| Library Path | Symbol library path relative to DbLib |
| Footprint Ref | Parsed footprint name |
| Footprint Path | Footprint library path relative to DbLib |
| InvenTree PK | Part.pk as canonical positive decimal text |

Ordinary columns follow in ascending template PK order; tables use category PK order and rows Part PK order. A parameter present on any Part contributes a column; Parts without it get None.

Ordinary names retain template spelling and allow Unicode/punctuation. Reject empty names, leading whitespace, control characters U+0000–001F/U+007F–009F and case-insensitive collisions with other columns or technical names. Do not trim trailing whitespace or rename invalid fields. No fixed 64-character limit applies. An ordinary InvenTree PK parameter is a conflict, not an alternative source.

## Data transformation

IPN is the component identifier; Part.name is never a fallback. Do not generate IPNs or parse them to recreate Value, Package or characteristics. InvenTree PK comes only from positive Part.pk as canonical text matching `[1-9][0-9]*`; it is globally unique across tables, not the SQLite primary key, and gets no extra index.

Description, Comment and other ordinary fields exist only when actual parameters supply them. Do not copy Part.description or synthesize Comment from Value. The schematic symbol's configured Comment uses `=Value`.

### Text and units

Format only ordinary values using Parameter.data and ParameterTemplate.units. Do not format technical fields or excluded CAD values. Preserve the source dataset; the writer preserves prepared strings exactly.

| Source data | Units | Prepared value |
|---|---|---|
| 0603 | empty | 0603 |
| =example | empty | =example |
| 10k | ohm | 10k ohm |
| 10 kΩ | ohm | 10 kΩ |
| 100n | F | 100n F |
| 10mV | V | 10mV |
| 1% | % | 1% |
| 1E3 | empty | 1E3 |
| null or empty string | any | None |
| whitespace only | any | unchanged whitespace |

Without units, preserve nonempty text verbatim. With units, recognize a signed scalar decimal magnitude (dot/comma, optional scientific notation) and inspect its suffix without numeric conversion. Append one space and the exact metadata units when absent; retain compatible existing suffixes. Never rescale, normalize decimal/SI spelling or needlessly replace ohm/Ω/Ω.

Recognized bases: V, A, F, H, W, Hz, s, m, g, K, °C, %, ohm, Ω, Ω. Prefixes: q r y z a f p n u µ μ m c d da h k M G T P E Z Y R Q. Exact custom units, optionally SI-prefixed, also work (rpm/krpm). This is suffix compatibility, not dimensional analysis/conversion.

Unknown/conflicting suffixes, non-scalar expressions with units, ambiguous bare m where not recognized as metres, and units with surrounding whitespace fail. Letter-decimal engineering text such as 4K7/4n7 is not a scalar for this formatter: keep display Value unitless and put numeric 4.7k/4.7n in the corresponding electrical parameter. Ranges with Hz are unsupported; see the [category metadata issue](../../docs/inventree-category-structure.md#питання-для-окремого-узгодження).

Errors include Part PK/IPN, category, template PK/name, source value and units. Never return partial tables or substitute placeholder strings None, NaN or NULL.

## Altium model references

Every Part requires actual, unambiguous, nonblank assignments:

```text
Altium Symbol = Passives:Resistor
Altium Footprint = Resistors:RES_0603_H0.55
```

`parse_model_ref(value, kind)` requires exactly one colon between library basename and model. Exact-case .SchLib/.PcbLib extensions are optional on the library portion. Paths, wrong extensions, whitespace/case repair and missing-library inference are rejected. Exact grammars are in the [library convention](../../docs/library-convention.md#accepted-reference-syntax). Package is neither a footprint reference nor a lookup key for automatic mapping.

LibraryLayout requires absolute native Paths for DbLib, symbols and footprints, resolved by the caller. Resolve the file under the configured library directory and require is_file(), caching each library check per preparation. Emit Windows-backslash paths relative to the **DbLib parent directory**. Standard examples: `..\symbols\Passives.SchLib` and `..\footprints\Resistors.PcbLib`. Different drives/shares that cannot be expressed relatively fail; no absolute fallback exists.

Within each model kind, exported model names must be unique case-insensitively across different libraries. Reusing the same model from the same library is valid. Symbol and footprint namespaces are separate. Validation checks references/file existence only, not binary library contents, internal model presence, pins or 3D assets.

## SQLite database

All columns are TEXT. The six technical columns are NOT NULL; IPN is PRIMARY KEY COLLATE NOCASE. Missing optional values become SQL NULL. Python global casefold IPN validation is stricter than SQLite's ASCII NOCASE. Canonical InvenTree PK values must also be globally unique. No auxiliary user tables, extra technical columns or InvenTree PK index are generated.

Validate identifiers, quote them with SQLite double quotes and escape embedded double quotes. Parameterize every value. Preserve textual leading zeros, exponents, percentages and equals signs without coercion/truncation.

Direct writer calls validate manually constructed PreparedTables too. In-memory validation creates the real schema and inserts every row with the installed engine. Integrity/schema/value checks are shared with disk verification. Engine limits produce errors, never silent omission.

The writer rejects an empty export/table, duplicate category PKs, wrong technical columns, CAD source columns, invalid template PKs or malformed rows. Row keys must exactly match column order; all non-null values must be strings and technical values nonblank. Writing does not reformat units, reparse model references or reconstruct source data.

## Database publication and recovery

Close Altium and other consumers first. The destination lock coordinates only inventree-sync processes; it cannot coordinate external readers or remove races with other applications.

1. Validate the export; acquire exclusive `<destination>.sync.lock` with ownership information. Never automatically expire or steal an existing lock.
2. Create unique staging in the destination directory. Build the whole snapshot in a transaction with DELETE rollback journaling and synchronous=FULL.
3. Commit and close. Reopen staging read-only; verify integrity_check, journal mode, exact tables/columns/constraints/primary-key collation and every row/value/NULL. Reject unexpected objects or data.
4. Close verification. Under the lock, inspect destination -wal, -shm and -journal **without opening the published database**. Every filesystem entry, including empty files, directories and dangling symlinks, blocks publication. Inspection failures also block it, even without an existing destination.
5. Publish with same-directory os.replace. Clean only owned staging artifacts and the owned lock, checking lock identity before removal.

Staging uses a unique `.<destination>.<random>.staging.sqlite` file. Verification requires `PRAGMA integrity_check = ok`, DELETE mode, ordered `table_xinfo` definitions (types, nullability, defaults, PK and hidden flags), and the single primary-key index/collation through `index_list`/`index_xinfo`. Compare all columns and row counts in IPN order using SQLite's ASCII NOCASE ordering. The writer may create the destination directory; in-memory validation never does.

Failures before replacement preserve existing database bytes. Windows sharing failures are reported; never force-close consumers. A post-replacement cleanup failure must identify that publication already occurred. Replacement alone does not guarantee safety for an actively used database.

Never checkpoint, repair or remove external journals. A sidecar blocks with code 4. Let the owning application complete normal transactions/recovery and journal cleanup; do not delete journals to bypass protection.

### Recovery procedure

- Configuration/data errors: correct the source or setting, then retry; do not patch the generated database to hide errors.
- API/auth/network errors: restore access and retry. Sync reports an existing snapshot unchanged and available offline while retaining its failure code.
- External locks/journals: close consumers normally and allow their recovery to finish; do not remove their files.
- Abandoned sync lock: verify the recorded owner is stopped and no synchronization to this destination is running; PID reuse is possible. Only then may an operator remove that stale lock and positively identified abandoned staging artifacts. Age alone is insufficient. Never delete the published database or its external journals. Retry to build a new snapshot.

### Tracked offline snapshot

[database/components.sqlite](../../database/components.sqlite) is an intentional tracked, verified offline snapshot, potentially older than InvenTree. A successful export removes obsolete rows/columns/tables and overwrites manual edits. There is no reverse synchronization.

Before tracking an update, verify integrity, expected schema/content and absence of journal dependencies. Do not fabricate sample data when production is unavailable. Other databases, stages, sidecars, locks and local configuration remain ignored. Runtime/build/CI never commit or push.

## Altium integration

[Components.DbLib](../../database/Components.DbLib) uses DSN=AltiumComponents through MSDASQL. The independent [setup utility](../setup-odbc/README.md) configures a Windows x64 User DSN for existing database/components.sqlite. It reads no TOML and does not follow custom sync.output. Use the standard location with this utility or manage a different connection manually.

Configure mappings manually:

| SQLite field | Altium role/target |
|---|---|
| IPN | Component lookup key |
| Library Ref | [Library Ref] |
| Library Path | [Library Path] |
| Footprint Ref | [Footprint Ref] |
| Footprint Path | [Footprint Path] |
| InvenTree PK | Ordinary InvenTree PK, without brackets |
| Value and other ordinary columns | Corresponding component parameters |

Symbol Comment uses =Value; no synthesized Comment column is needed. An explicit ordinary Comment parameter exports normally. Category changes/reclassification can replace tables and require manual DbLib mapping changes; template renames similarly change fields. Neither executable rewrites mappings.

ODBC verification does not prove Altium placement or every table mapping. Manually check Connect, IPN lookup, parameters, symbol placement and footprint transfer.

## Building the Windows executable

From Windows with Python 3.11+:

```powershell
.\tools\inventree-sync\build.ps1
```

If execution policy blocks scripts, use a process-only invocation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\inventree-sync\build.ps1
```

The script resolves paths from PSScriptRoot; -Python selects the interpreter for initial environment creation. It uses the single ignored .venv, checks Python 3.11+, installs test/build extras and runs the full suite. It builds a unique onefile/console PyInstaller candidate from src/run.py under build/, then runs real executable smoke tests before atomically replacing tools/inventree-sync.exe. Failures preserve the old executable. Clean only owned candidates; no launcher, permanent distribution directory or archive is produced.

Frozen execution needs no Python installation. Console ownership detection keeps Explorer-owned interactive consoles open for Enter on success/help/errors, preserving exit codes. Account for the PyInstaller parent/child pair. Existing terminals, redirected streams and CI never pause; uncertain detection must not block automation.

The [Windows workflow](../../.github/workflows/inventree-sync-windows.yml) uses Python 3.11 and uploads the final executable directly. It never commits, pushes or builds the independent ODBC utility.

## Testing

Ordinary tests use anonymized fixtures/mocks without production credentials, a live server, ODBC or Altium. They cover HTTP/auth/pagination/retries, nested metadata/scope, mixed schemas/exclusions, model references/paths, text/units, direct writer validation, lock/sidecar failures, previous snapshot preservation, configuration, CLI, console and build policies.

Real executable tests are opt-in outside builds with `--sync-executable <absolute-exe-path>`; see [tests/conftest.py](tests/conftest.py). They use disposable layouts/unrelated cwd, missing/invalid config, help/errors and terminal/Explorer console scenarios. Never use production credentials or modify tracked outputs. Report platform prerequisite skips. Native ODBC integration belongs to the [setup-odbc suite](../setup-odbc/README.md#verification).

## Error handling and exit codes

| Code | Meaning |
|---|---|
| 0 | Command completed successfully |
| 1 | Unexpected internal/runtime failure |
| 2 | Configuration, input or source/export validation error |
| 3 | API, authentication, authorization or transport failure |
| 4 | Database, filesystem, lock, verification or publication failure |

Expected failures are concise and contextual, with Part PK/IPN, category PK/path, template PK/name and affected paths where applicable. Normal unexpected-error output does not expose tracebacks or secrets. Failure must not be presented as a successful empty export or successful offline synchronization.

## Limitations

The application supports the documented response contract, not arbitrary API schemas or automatic fallbacks. It cannot see permission-hidden children or guarantee transactional consistency across server requests. It validates exported references, not library binary contents, pin compatibility, geometry or electrical interchangeability. Unit formatting is limited scalar suffix handling. Category/IPN engineering conventions are human-maintained, not runtime data generators. SQLite tests do not establish installed-driver or Altium compatibility.

Known diagnostic discrepancy: the error for an unsupported `[inventree]` setting still says credentials must use environment variables. That wording describes legacy token mode, not the current interactive Basic contract. A future code fix should correct the message; it does not justify storing Basic credentials in the environment.
