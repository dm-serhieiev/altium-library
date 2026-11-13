"""Build and verify complete SQLite snapshots, then publish by atomic replace."""

from contextlib import closing, contextmanager
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Iterator

from .categories import CategoryError, validate_table_name
from .models import PreparedTables, TECHNICAL_COLUMNS
from .schema import EXCLUDED_EXPORT_PARAMETERS
from .validate import ExportValidationError, validate_column_name, validate_columns, validate_row


class DatabaseError(RuntimeError):
    """Database construction, verification, locking or publication failed."""


_ASCII_NOCASE = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def quote_identifier(name: str) -> str:
    """Quote a validated identifier, including embedded double quotes."""
    validate_column_name(name)
    return '"' + name.replace('"', '""') + '"'


def _validate_prepared(prepared: PreparedTables) -> None:
    """Defend the public writer boundary, including manually assembled tables."""
    if not prepared.tables:
        raise ExportValidationError("No exported component tables")
    names: set[str] = set()
    categories: set[int] = set()
    ipns: dict[str, str] = {}
    part_pks: dict[str, str] = {}
    for table in prepared.tables:
        context = f"Table {table.name!r}, category pk={table.category_pk} path={table.category_path!r}"
        try:
            validate_table_name(table.name)
        except CategoryError as exc:
            raise ExportValidationError(f"{context}: {exc}") from None
        if table.name.casefold() in names or table.category_pk in categories:
            raise ExportValidationError(f"{context}: duplicate table name or category PK")
        names.add(table.name.casefold())
        categories.add(table.category_pk)
        validate_columns(table.columns, context)
        if table.columns[:len(TECHNICAL_COLUMNS)] != TECHNICAL_COLUMNS:
            raise ExportValidationError(f"{context}: expected the six ordered technical columns")
        templates: set[int] = set()
        for column in table.columns[len(TECHNICAL_COLUMNS):]:
            if column.name in EXCLUDED_EXPORT_PARAMETERS:
                raise ExportValidationError(f"{context}: source-only CAD column {column.name!r} must not be exported")
            if type(column.template_pk) is not int or column.template_pk <= 0 or column.template_pk in templates:
                raise ExportValidationError(f"{context}, column {column.name!r}: expected a unique positive template PK")
            templates.add(column.template_pk)
        if not table.rows:
            raise ExportValidationError(f"{context}: empty component tables must not be exported")
        for number, row in enumerate(table.rows, 1):
            source = f"{context}, row {number} IPN={row.get('IPN')!r}"
            validate_row(row, table.columns, source)
            ipn = row["IPN"]
            assert isinstance(ipn, str)  # validate_row requires nonempty technical strings.
            key = ipn.casefold()
            if key in ipns:
                raise ExportValidationError(f"{source}: duplicate IPN with {ipns[key]}")
            ipns[key] = source
            part_pk = row["InvenTree PK"]
            if part_pk in part_pks:
                raise ExportValidationError(f"{source}: duplicate InvenTree PK {part_pk!r} with {part_pks[part_pk]}")
            part_pks[part_pk] = source


def _populate(connection: sqlite3.Connection, prepared: PreparedTables) -> None:
    """DDL and parameterized inserts share a single explicit transaction."""
    with connection:
        connection.execute("BEGIN")
        for table in prepared.tables:
            declarations = []
            for column in table.columns:
                constraint = ""
                if column.name == "IPN":
                    constraint = " NOT NULL PRIMARY KEY COLLATE NOCASE"
                elif column.template_pk is None:
                    constraint = " NOT NULL"
                declarations.append(f"{quote_identifier(column.name)} TEXT{constraint}")
            identifier = quote_identifier(table.name)
            columns = ", ".join(quote_identifier(c.name) for c in table.columns)
            placeholders = ", ".join("?" for _ in table.columns)
            try:
                connection.execute(f"CREATE TABLE {identifier} ({', '.join(declarations)})")
                connection.executemany(
                    f"INSERT INTO {identifier} ({columns}) VALUES ({placeholders})",
                    (tuple(row[c.name] for c in table.columns) for row in table.rows),
                )
            except sqlite3.Error as exc:
                raise sqlite3.DatabaseError(f"Table {table.name!r}: {exc}") from None


def _verify_connection(connection: sqlite3.Connection, prepared: PreparedTables) -> None:
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise DatabaseError("SQLite integrity_check failed")
    objects = connection.execute("SELECT type, name, tbl_name FROM sqlite_schema WHERE type != 'index'").fetchall()
    expected_objects = {("table", table.name, table.name) for table in prepared.tables}
    if set(objects) != expected_objects:
        raise DatabaseError("SQLite verification: component table set differs, or unexpected schema objects exist")
    for table in prepared.tables:
        identifier = quote_identifier(table.name)
        info = connection.execute(f"PRAGMA table_xinfo({identifier})").fetchall()
        expected_info = [
            (i, c.name, "TEXT", int(c.template_pk is None), None, int(c.name == "IPN"), 0)
            for i, c in enumerate(table.columns)
        ]
        if info != expected_info:
            raise DatabaseError(f"Table {table.name!r}: ordered columns, TEXT types or required constraints differ")
        indexes = connection.execute(f"PRAGMA index_list({identifier})").fetchall()
        if len(indexes) != 1 or indexes[0][2:] != (1, "pk", 0):
            raise DatabaseError(f"Table {table.name!r}: expected exactly one primary-key index")
        index = quote_identifier(indexes[0][1])
        keys = [row for row in connection.execute(f"PRAGMA index_xinfo({index})") if row[-1]]
        if keys != [(0, 0, "IPN", 0, "NOCASE", 1)]:
            raise DatabaseError(f"Table {table.name!r}: IPN primary key must use NOCASE collation")
        columns = ", ".join(quote_identifier(c.name) for c in table.columns)
        stored = connection.execute(f'SELECT {columns} FROM {identifier} ORDER BY "IPN"').fetchall()
        expected = [
            tuple(row[c.name] for c in table.columns)
            for row in sorted(table.rows, key=lambda row: row["IPN"].translate(_ASCII_NOCASE))
        ]
        if len(stored) != len(expected):
            raise DatabaseError(f"Table {table.name!r}: expected {len(expected)} rows, found {len(stored)}")
        for actual, original in zip(stored, expected):
            if actual != original:
                raise DatabaseError(f"Table {table.name!r}, expected IPN={original[0]!r}: stored values differ from PreparedTables")


def validate_sqlite_tables(prepared: PreparedTables) -> None:
    """Exercise real SQLite schema, constraints and data in memory; no files."""
    _validate_prepared(prepared)
    try:
        connection = sqlite3.connect(":memory:")
    except sqlite3.Error as exc:
        raise DatabaseError(f"Cannot open in-memory SQLite validation database: {exc}") from None
    try:
        with closing(connection):
            connection.execute("PRAGMA temp_store=MEMORY")
            _populate(connection, prepared)
            _verify_connection(connection, prepared)
    except (sqlite3.Error, UnicodeError, OverflowError) as exc:
        raise ExportValidationError(f"SQLite schema/data compatibility error: {exc}") from None


def _write_staging(prepared: PreparedTables, staging: Path) -> None:
    with closing(sqlite3.connect(staging)) as connection:
        mode = connection.execute("PRAGMA journal_mode=DELETE").fetchone()
        if mode != ("delete",):
            raise DatabaseError(f"Staging database {staging}: cannot enable DELETE journal mode")
        connection.execute("PRAGMA synchronous=FULL")
        _populate(connection, prepared)


def _verify_database(prepared: PreparedTables, staging: Path) -> None:
    # as_uri escapes spaces, # and ? in native paths before adding mode=ro.
    with closing(sqlite3.connect(staging.as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA journal_mode").fetchone() != ("delete",):
            raise DatabaseError(f"Staging database {staging}: expected DELETE journal mode")
        _verify_connection(connection, prepared)


def _check_destination_state(destination: Path) -> None:
    """Fail closed on destination sidecars, without opening or repairing SQLite.

    lstat detects entries even when they are dangling symlinks. This is a final
    guard, not a lock against non-cooperating external SQLite consumers.
    """
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(destination) + suffix)
        try:
            sidecar.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise DatabaseError(f"Database publication blocked for {destination}: cannot inspect SQLite sidecar {sidecar}: {exc}") from None
        raise DatabaseError(
            f"Database publication blocked for {destination}: SQLite journal/sidecar exists: {sidecar}. "
            "Close applications using the database and ensure SQLite has completed its transactions before retrying."
        )


@contextmanager
def _destination_lock(destination: Path) -> Iterator[None]:
    lock = destination.with_name(destination.name + ".sync.lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise DatabaseError(f"Synchronization lock exists: {lock}; another or interrupted sync may own it. Confirm no owner is running before manual recovery.") from None
    identity = None
    try:
        identity = os.fstat(descriptor)
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        yield
    finally:
        os.close(descriptor)
        # Never unlink a replacement lock created by someone else.
        try:
            current = lock.stat(follow_symlinks=False)
        except FileNotFoundError:
            current = None
        if identity is not None and current is not None and (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
            lock.unlink()


def write_sqlite_database(prepared: PreparedTables, destination: Path) -> None:
    """Validate, stage, close, reopen read-only, verify, then atomically publish.

    Only files created by this operation are cleaned up. Existing destination
    bytes are untouched until os.replace succeeds. No readers are force-closed.
    """
    validate_sqlite_tables(prepared)
    staging: Path | None = None
    published = False
    try:
        destination = Path(destination).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with _destination_lock(destination):
            try:
                descriptor, filename = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".staging.sqlite", dir=destination.parent)
                staging = Path(filename)
                os.close(descriptor)
                _write_staging(prepared, staging)
                _verify_database(prepared, staging)
                _check_destination_state(destination)
                os.replace(staging, destination)
                published = True
            finally:
                if staging is not None:
                    for owned in (staging, Path(str(staging) + "-journal")):
                        owned.unlink(missing_ok=True)
    except (DatabaseError, OSError, sqlite3.Error) as exc:
        state = "published, but cleanup failed" if published else "not published; previous database preserved"
        raise DatabaseError(f"Database {destination}: {state}: {exc}") from None
