# Repository Agent Instructions

This file defines the rules for AI coding agents working in this repository.

The repository contains the Altium component library, InvenTree integration tools, library conventions, and supporting documentation.

The documentation in the repository is part of the project specification. Read the relevant documentation before modifying code or library data.

---

## 1. General working rules

Before making changes:

1. Inspect the existing repository structure.
2. Read the documentation relevant to the requested task.
3. Reuse existing naming conventions, architecture, modules, and file locations.
4. Check whether the requested behavior is already defined by an architecture or convention document.
5. Do not redesign established architecture simply because another implementation would be easier.

Prefer small, reviewable changes over broad unrelated refactoring.

Do not modify files unrelated to the requested task unless the change is necessary and clearly explained.

If implementation reveals a conflict, ambiguity, or technical limitation in the existing specification, report it explicitly. Do not silently resolve architectural conflicts by inventing new behavior.

---

## 2. Documentation hierarchy

For `inventree-sync`, the authoritative architecture document is:

```text
docs/architecture/inventree-sync-design.md
```

Relevant component-library conventions are located under:

```text
docs/conventions/
```

and include documents such as:

```text
inventree-category-structure.md
ipn-naming-convention.md
library-convention.md
```

Architecture documents define how software is expected to work.

Convention documents define naming and library rules.

Markdown documentation is intended for humans and agents. Runtime synchronization code must not parse these Markdown files as a source of component data unless explicitly required by the architecture.

When implementation and documentation disagree, do not silently alter either side. Report the discrepancy and identify the affected files and behavior.

---

## 3. InvenTree is the source of truth

InvenTree is the single source of truth for component-library data.

The following information must be obtained dynamically from InvenTree where required by the synchronization process:

- component categories and category hierarchy;
- Parts;
- Part IPNs;
- actual parameters attached to each Part;
- parameter templates and their metadata;
- other InvenTree metadata required by the synchronization architecture.

InvenTree itself is responsible for category parameter assignment and inheritance. When a Part is created, the concrete Part exposes the parameters that apply to it, including parameters inherited from higher-level categories. `inventree-sync` must consume those actual Part parameters and must not reconstruct category-parameter inheritance locally.

Do not duplicate component data in repository configuration files.

In particular, do not create local configuration files containing hard-coded copies of:

- the current category tree;
- category-specific parameter lists;
- inherited parameter lists;
- units;
- choice lists;
- current leaf-category lists.

Changes made in InvenTree should be reflected by synchronization without requiring corresponding edits to repository configuration unless the change affects an actual synchronization rule or software contract.

---

## 4. Synchronization direction

Synchronization is strictly one-way:

```text
InvenTree -> prepared logical tables -> generated database -> Altium DbLib
```

Milestone 1C introduces database-independent `PreparedTables`. Milestone 1D
selects SQLite as the only supported database backend. Microsoft Access is no
longer planned or supported. The logical stage must not generate SQL or database
files. `prepare_tables(dataset, layout)` remains a separate Python API. `inspect`
reads source data, `validate` exercises the complete export in memory, and `sync`
publishes a verified SQLite snapshot using `sqlite.py`.

`inventree-sync` must never modify InvenTree.

Do not implement API operations which create, update, move, rename, or delete InvenTree objects unless a future task explicitly changes this architectural rule.

The generated SQLite `.sqlite` database is a reproducible intermediate artifact.

It is not a source of truth.

Manual changes made to the generated database are not preserved and must not be synchronized back to InvenTree.

The Altium `.DbLib` consumes the generated SQLite database through the separately configured SQLite ODBC connection but is not a source of component data for `inventree-sync`. Never modify `.DbLib`, `.SchLib`, or `.PcbLib` files during synchronization. Do not synthesize a `Comment` column from `Value`; the tested schematic symbol Comment uses `=Value`. An explicit ordinary InvenTree `Comment` parameter is exported normally.

---

## 5. `inventree-sync` architecture

Before modifying `inventree-sync`, read:

```text
docs/architecture/inventree-sync-design.md
```

Follow the module boundaries and contracts defined there.

The program name and console command are:

```text
inventree-sync
```

The Python package is:

```text
inventree_sync
```

The synchronization implementation belongs under:

```text
tools/inventree-sync/
```

Do not introduce a substantially different package structure without a concrete technical reason.

If the architecture document specifies a module responsibility, keep that responsibility in the corresponding module rather than duplicating logic elsewhere.

---

## 6. Dynamic schema generation

The database schema must be derived from the actual parameters of exported InvenTree Parts.

Only a leaf category containing at least one exported Part produces a SQLite component table.

For each exported leaf category, the program must determine:

```text
leaf category
        ->
exported Parts in that category
        ->
actual parameters of all Parts
        ->
union of referenced parameter templates
        ->
effective table schema
```

InvenTree already applies parameters inherited from higher-level categories to the concrete Part. `inventree-sync` must therefore read the parameters that actually exist on each Part and must not reconstruct category inheritance.

Do not use category parameter assignments or a locally maintained category schema to determine columns.

An empty leaf category produces no SQLite table and does not require schema discovery.

If an ordinary parameter exists on at least one Part in the category, it belongs to the table schema. Parts which do not contain that parameter receive Python `None` (eventually SQL `NULL`) for that column. Dynamic columns remain ordered by ParameterTemplate PK after the five technical columns.

Validate all actual parameter references before excluding these exact template names from the output schema: `KiCad Symbol`, `KiCad Footprint`, `Altium Symbol`, `Altium Footprint`. KiCad values are ignored by Altium transformation. The two Altium parameters are mandatory source-only parameters; resolve them through `PreparedDataset.parameters` and `PreparedDataset.templates`, independently of exported columns. Keep all source parameters and templates in `PreparedDataset`.

Do not hard-code the expected schema of categories such as Resistors, Capacitors, Inductors, or Transformers in Python or TOML merely to reproduce the current InvenTree state.

Adding, removing, or changing actual Part parameters in InvenTree should be reflected by the next synchronization without modifying repository configuration.

---

## 7. Fixed synchronization contracts

Some rules are software contracts rather than InvenTree data and therefore may be implemented explicitly.

Examples include:

- `Part.IPN` maps to the database `IPN`;
- `IPN` is the component identifier used by the generated Altium database;
- `Part.name` is not an IPN fallback;
- IPNs are not regenerated from other parameters;
- IPNs are not parsed to recreate Value, Package, or electrical characteristics;
- one InvenTree Part produces one component row;
- Stock Items do not create component rows;
- Supplier Parts do not create component rows;
- Manufacturer Parts do not create component rows;
- one non-empty exported leaf InvenTree category maps to one SQLite component table;
- the table name is exactly the leaf category name;
- invalid table names are validation errors and are not automatically rewritten.

Technical Altium fields and conversion rules defined by the architecture are also synchronization contracts.

Do not confuse these fixed conversion rules with component data which belongs in InvenTree.

---

## 8. Altium model references

The parameters:

```text
Altium Symbol
Altium Footprint
```

have special meaning to `inventree-sync`.

They generate only `Library Ref`, `Library Path`, `Footprint Ref`, and `Footprint Path`; their original values must not become output columns. Exclusion does not relax required-assignment, reference-format, library-file existence or global model-name uniqueness checks.

Follow the exact format and parsing rules defined in:

```text
docs/architecture/inventree-sync-design.md
```

Do not infer missing library names.

Do not substitute:

```text
Package
```

for an Altium footprint.

Do not substitute Part names, descriptions, IPNs, or other fields for missing model references.

If a required model reference is missing or malformed, report a validation error instead of silently correcting the source data.

---

## 9. Source data must not be silently repaired

Do not silently modify data obtained from InvenTree to make synchronization succeed.

In particular, do not automatically:

- rename IPNs;
- rename categories;
- sanitize category names into different SQLite table names;
- derive missing parameters from IPNs;
- derive missing parameters from `Part.name`;
- derive missing parameters from `Part.description`;
- infer missing symbol libraries;
- infer missing footprint libraries;
- normalize engineering units;
- change SI prefixes;
- change decimal separators;
- reinterpret textual parameter values as numbers;
- replace missing values with arbitrary defaults.

If source data violates a project rule, validation should identify the problem and provide enough context to correct it at the source.

---

## 10. Preserve textual parameter data

Unless explicitly required otherwise by the architecture, treat InvenTree parameter values as textual data.

Preserve values such as:

```text
0603
1%
1E3
10 kΩ
=example
```

without unintended numeric conversion or formatting changes.

Use the textual InvenTree parameter representation defined by the architecture.

`PreparedDataset` retains the original source representation. In the transformation layer only, `PreparedTables` formats ordinary parameter values using `Parameter.data` and `ParameterTemplate.units`, never `data_numeric`. Append missing units using the exact metadata spelling and one added space; preserve existing equivalent suffixes (especially `ohm`/`Ω`/`Ω`) without duplication or conversion. Do not format the five technical columns or excluded CAD parameters. Conflicting or ambiguous unit suffixes must raise contextual `ExportValidationError` with Part PK/IPN, template PK/name, original value and configured units; never return partial tables. Supported scalar/suffix recognition and its limits are specified in the architecture document. Missing/empty values remain `None`; whitespace-only optional values remain verbatim even with units.

Missing optional values should remain missing and ultimately map to SQL `NULL`, not placeholder strings such as:

```text
None
NaN
NULL
```

---

## 11. Configuration and secrets

Repository configuration describes synchronization behavior and environment-specific locations.

It must not duplicate the InvenTree component database.

Never commit:

- API tokens;
- passwords;
- Authorization headers;
- session cookies;
- other credentials.

Use environment variables or secure interactive input as specified by the architecture.

Do not log secrets.

Do not include secrets in generated reports, exceptions, debug dumps, fixtures, or test snapshots.

Example configuration files must contain placeholders only.

Local configuration files containing real server addresses or credentials should remain untracked where appropriate.

---

## 12. API implementation

Keep InvenTree HTTP behavior isolated from the rest of the application according to the architecture.

The primary retrieval contract targets InvenTree 1.5.6 / API schema 530. Follow
`docs/architecture/inventree-sync-design.md`, section 3: fetch all accessible
categories, resolve the configured root PK, then request Parts with
`category=<root_pk>&cascade=true&parameters=true` on every page. Do not download
all Parts and discard those outside scope. Build shared parameter/template
indexes from actual nested parameters and `template_detail`; conflicting
template metadata or missing nested data must fail explicitly. Do not add
automatic fallback or separate parameter/template requests to this path.
Server-side filtering does not replace local category and Part validation.
The read-only `inspect` command uses this workflow and must not create SQLite
output or claim full validation/synchronization.

Raw API JSON must not leak unnecessarily into category, schema, transformation, or SQLite-writing logic.

Use the adapter layer for API-version-specific response structures.

Do not guess undocumented API behavior when it can be determined from the actual server API/schema.

Handle pagination completely.

Do not interpret:

- authorization failure;
- HTTP failure;
- malformed pagination;
- unsupported API schema

as an empty dataset.

Read operations must remain read-only.

---

## 13. SQLite generation and publication safety

The generated `.sqlite` is a build artifact. Use only standard-library `sqlite3`; do not introduce backend selection, an ORM, database credentials or an external database-generation driver.

Build a complete snapshot from `PreparedTables`, never incrementally modify the published database. All columns are `TEXT`; the five technical columns are `NOT NULL`, and `IPN` is `PRIMARY KEY COLLATE NOCASE`. Optional missing values become SQL `NULL`. Preserve prepared strings and units exactly; never reformat them in the writer. Enforce global case-insensitive IPN uniqueness across tables. Direct writer calls must validate manually constructed tables too.

Create a unique staging file in the destination directory, use a transaction with DELETE rollback journaling and normal synchronization, commit and close it, reopen read-only and verify integrity, exact tables/schema/constraints and every stored value. Close verification before `os.replace`. Never publish an incomplete database. Do not add auxiliary user tables or columns.

Acquire an exclusive `<destination>.sync.lock` before staging/publication. Never remove a lock belonging to another active or potentially interrupted process. Recover stale locks manually only after confirming the owning process is stopped, as described in the architecture. Clean up only staging artifacts and locks owned by this operation.

All configured filesystem paths are relative to the TOML directory. `[sync]` output/dblib and `[libraries]` symbols/footprints are required for validate/sync; inspect still supports only `[inventree]` and `[scope]`. No database file or output directory is created by validate.

Do not force-close Altium or another process holding the database, and do not remove their lock/journal files.

A failed synchronization must leave the previously published database intact.

---

## 14. SQL safety

Validate table and field identifiers before using them in SQL.

Do not attempt to pass identifiers through SQL value placeholders.

Use parameterized queries for values.

Never concatenate InvenTree parameter values directly into SQL statements.

Quote validated identifiers with SQLite double quotes, escaping embedded quotes. Retain the English category naming convention, reject sqlite_ internal table names and case-insensitive collisions. Access-specific reserved words and 64-character table/field limits no longer apply. Parameter names allow punctuation and Unicode, but not leading whitespace or control characters. Never silently rename identifiers or truncate values.

If the installed SQLite engine's schema or size limits are exceeded, fail validation or publication clearly.

---

## 15. Coding style

Target the Python version specified by the architecture.

Prefer:

- standard library functionality where practical;
- dataclasses for simple internal models;
- explicit type hints;
- `pathlib` for filesystem paths;
- `logging` for diagnostics;
- small focused functions;
- clear exceptions with useful context.

Avoid unnecessary:

- frameworks;
- ORMs;
- dependency-injection frameworks;
- global mutable state;
- metaprogramming;
- complex inheritance hierarchies;
- abstractions with only one trivial implementation.

Do not add a dependency when the standard library reasonably solves the problem.

Keep functions deterministic where practical so that they can be unit tested without network or database access.

---

## 16. Error handling

Errors should contain enough context to identify the source object.

Where applicable include:

- Part PK;
- IPN;
- category PK;
- full category path;
- parameter-template PK;
- parameter name;
- affected file path.

Do not hide validation errors behind generic messages such as:

```text
Invalid data
```

Expected user/data/API errors should be handled cleanly by the CLI.

Unexpected exceptions may expose traceback information in debug mode, but normal CLI output should remain concise.

Follow the exit-code contract defined by the architecture.

---

## 17. Testing

Every implemented behavior should have appropriate automated tests.

Unit tests must not require:

- access to the production InvenTree server;
- real API credentials;
- a database ODBC driver;
- Altium Designer.

Use anonymized fixtures and mocks for these dependencies.

Tests involving the real Windows / ODBC / Altium environment should be clearly separated as integration tests.

When fixing a bug, add a regression test whenever practical.

Do not weaken or delete an existing test merely to make new implementation code pass unless the old test contradicts an explicitly changed requirement.

---

## 18. Fixtures

API fixtures must be:

- anonymized;
- minimal;
- representative of supported API responses;
- free of credentials and private production data.

Prefer several small focused fixtures over large raw dumps of the production InvenTree database.

Fixtures should cover edge cases such as pagination, missing values, empty leaf categories being ignored, Parts with different parameter sets, malformed references, and API errors where relevant.

---

## 19. Documentation changes

Code changes which alter externally visible behavior, architecture, configuration, or assumptions should update the relevant documentation.

Do not change architecture documentation merely to justify an implementation shortcut.

If a requested implementation requires changing an agreed architectural rule:

1. identify the conflict;
2. explain why the current design cannot or should not be followed;
3. propose the smallest necessary architecture change;
4. keep implementation and documentation changes clearly separated for review where practical.

Historical architecture decisions should not be silently erased.

---

## 20. Git and scope discipline

Keep changes focused on the current task.

Before finishing:

- inspect the complete diff;
- remove accidental or unrelated changes;
- ensure generated temporary files are not committed;
- ensure credentials are not committed;
- run the relevant tests;
- report any tests which could not be run.

Do not create commits, branches, tags, releases, or pull requests unless the task explicitly requests them or the execution environment specifically requires them.

Do not modify Git history.

Do not force-push.

---

## 21. Generated files

Do not commit generated synchronization output unless repository policy explicitly requires it.

Examples of files which are normally generated or local include:

```text
database/components.sqlite
*.staging.sqlite
*.staging.sqlite-journal
*.sync.lock
tools/inventree-sync/config.toml
```

Do not remove unrelated historical artifacts as part of SQLite implementation or documentation cleanup. SQL fixtures and other intentionally maintained source files must remain trackable.

Respect the repository `.gitignore`.

---

## 22. Before completing a task

Before reporting completion:

1. Re-read the original task.
2. Check the implementation against `AGENTS.md`.
3. Check it against the relevant architecture and convention documents.
4. Review the diff for unrelated changes.
5. Run the relevant tests.
6. Run formatting/linting/type checks if the repository defines them.
7. Verify that no secrets or local environment files were added.
8. Identify any assumptions made.
9. Identify any requirements which could not be implemented or tested.

Do not report a task as complete if known required behavior is still missing.

---

## 23. Final task report

After implementing a task, provide a concise report containing:

- summary of implemented behavior;
- files created;
- files modified;
- tests executed and their results;
- assumptions made;
- limitations or unverified environment-specific behavior;
- architecture discrepancies discovered, if any.

Do not present untested environment-specific behavior as verified.

For example, SQLite unit tests do not prove compatibility with the installed SQLite ODBC driver or Altium DbLib. The user's successful sample-database ODBC test does not verify every generated production table. Clearly distinguish unit-tested behavior from real integration verification.

---

## 24. Core principle

When uncertain whether information belongs in repository configuration or should be obtained from InvenTree, use this rule:

> Component-library data belongs in InvenTree.  
> Synchronization behavior and conversion rules belong in the repository.

Do not create a second component database in configuration files.
