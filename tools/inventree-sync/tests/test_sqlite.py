from contextlib import closing
from dataclasses import replace
import sqlite3
from unittest.mock import Mock

import pytest

from inventree_sync import sqlite as writer
from inventree_sync.models import ColumnDefinition, PreparedTables, TECHNICAL_COLUMNS
from inventree_sync.transform import prepare_tables
from inventree_sync.validate import ExportValidationError


@pytest.fixture
def prepared(export_dataset, library_layout):
    return prepare_tables(export_dataset, library_layout)


def one_table(prepared, **changes):
    return PreparedTables((replace(prepared.tables[0], **changes),))


def test_complete_database_round_trip(prepared, tmp_path):
    destination = tmp_path / "new directory # Unicode" / "components.sqlite"
    before = repr(prepared)
    writer.write_sqlite_database(prepared, destination)
    assert repr(prepared) == before
    with closing(sqlite3.connect(destination)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert connection.execute("SELECT name FROM sqlite_schema WHERE type='table'").fetchall() == [("Resistors",)]
        info = connection.execute('PRAGMA table_info("Resistors")').fetchall()
        assert [r[1] for r in info] == [c.name for c in prepared.tables[0].columns]
        assert all(r[2] == "TEXT" for r in info)
        assert [r[3] for r in info] == [1] * 5 + [0] * 3
        assert [r[5] for r in info] == [1] + [0] * 7
        assert connection.execute('SELECT "Package", typeof("Package"), "Power Rating" FROM "Resistors" ORDER BY "IPN"').fetchall() == [
            ("0603", "text", None), (None, "null", "0.125 W"),
        ]
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute('INSERT INTO "Resistors" SELECT lower("IPN"), "Library Ref", "Library Path", "Footprint Ref", "Footprint Path", "Value", "Package", "Power Rating" FROM "Resistors" LIMIT 1')
    writer._verify_database(prepared, destination.resolve())
    assert sorted(p.name for p in destination.parent.iterdir()) == [destination.name]


@pytest.mark.parametrize("value", [
    "0603", "10k", "10k ohm", "0.125 W", "1%", "1E3", "=Value", "10 kΩ",
    "O'Brien", 'x"); DROP TABLE "Resistors"; --', "  exact text  ", "", None, "long" * 10000,
    "embedded\x00null", "Unicode μФ漢字",
], ids=lambda value: (value[:30] if isinstance(value, str) else "null"))
def test_writer_does_not_transform_or_truncate_values(prepared, tmp_path, value):
    table = prepared.tables[0]
    rows = ({**table.rows[0], "Value": value}, *table.rows[1:])
    snapshot = one_table(prepared, rows=rows)
    destination = tmp_path / "output" / "components.sqlite"
    writer.write_sqlite_database(snapshot, destination)
    with closing(sqlite3.connect(destination)) as connection:
        result = connection.execute('SELECT "Value" FROM "Resistors" WHERE "IPN" = ?', (rows[0]["IPN"],)).fetchone()
        assert result == (value,)


@pytest.mark.parametrize("name", ["Select", "GROUP BY", "MSysData", "Resistors" * 20])
def test_quoted_table_names_and_long_identifiers(prepared, tmp_path, name):
    table = prepared.tables[0]
    columns = (*table.columns, ColumnDefinition('A long "quoted" . ! ` [field] ' * 5, 200))
    rows = tuple({**row, columns[-1].name: "preserved"} for row in table.rows)
    snapshot = one_table(prepared, name=name, columns=columns, rows=rows)
    destination = tmp_path / "output" / "components.sqlite"
    writer.write_sqlite_database(snapshot, destination)
    writer._verify_database(snapshot, destination.resolve())


def test_identifier_quoting():
    assert writer.quote_identifier('Quoted "Name"') == '"Quoted ""Name"""'
    assert writer.quote_identifier("Select") == '"Select"'
    with pytest.raises(ExportValidationError):
        writer.quote_identifier("Bad\x00Name")


def test_multiple_tables_and_case_insensitive_global_ipns(prepared, tmp_path):
    first = prepared.tables[0]
    second = replace(first, category_pk=4, name="Connectors", rows=({**first.rows[0], "IPN": "CON-ONE"},))
    snapshot = PreparedTables((first, second))
    destination = tmp_path / "output" / "components.sqlite"
    writer.write_sqlite_database(snapshot, destination)
    writer._verify_database(snapshot, destination.resolve())
    duplicate = replace(second, rows=({**second.rows[0], "IPN": first.rows[0]["IPN"].lower()},))
    before = destination.read_bytes()
    with pytest.raises(ExportValidationError, match="duplicate IPN.*Resistors"):
        writer.write_sqlite_database(PreparedTables((first, duplicate)), destination)
    assert destination.read_bytes() == before


@pytest.mark.parametrize("defect", [
    "empty_export", "empty_table", "duplicate_table", "case_table_collision", "duplicate_category",
    "internal_name", "invalid_table", "duplicate_column", "case_column_collision",
    "invalid_column", "technical_order", "missing_technical", "extra_technical",
    "duplicate_template", "missing_template", "cad_column", "missing_cell", "extra_cell",
    "wrong_row_order", "numeric_value", "null_technical", "empty_technical", "blank_technical",
    "duplicate_ipn", "case_ipn_collision",
])
def test_manual_prepared_tables_fail_before_creating_files(prepared, tmp_path, defect):
    table = prepared.tables[0]
    columns = table.columns
    rows = tuple(dict(row) for row in table.rows)
    if defect == "empty_export":
        snapshot = PreparedTables(())
    elif defect in {"duplicate_table", "case_table_collision", "duplicate_category"}:
        other = replace(table, category_pk=99, name=table.name.lower() if defect == "case_table_collision" else table.name)
        if defect == "duplicate_category":
            other = replace(other, category_pk=table.category_pk, name="Other")
        snapshot = PreparedTables((table, other))
    else:
        if defect == "empty_table":
            rows = ()
        elif defect == "internal_name":
            table = replace(table, name="SQLite_internal")
        elif defect == "invalid_table":
            table = replace(table, name="Bad.Name")
        elif defect in {"duplicate_column", "case_column_collision", "invalid_column"}:
            name = {"duplicate_column": "Value", "case_column_collision": "vAlUe", "invalid_column": "Bad\nName"}[defect]
            columns = (*columns, ColumnDefinition(name, 200))
        elif defect == "technical_order":
            columns = tuple(reversed(columns))
        elif defect == "missing_technical":
            columns = columns[1:]
        elif defect == "extra_technical":
            columns = (*columns, ColumnDefinition("Unknown Technical", None))
        elif defect in {"duplicate_template", "missing_template", "cad_column"}:
            columns = (*columns, ColumnDefinition("Altium Symbol" if defect == "cad_column" else "Extra", 30 if defect == "duplicate_template" else None if defect == "missing_template" else 200))
        elif defect == "missing_cell":
            del rows[0]["Value"]
        elif defect == "extra_cell":
            rows[0]["Extra"] = "text"
        elif defect == "wrong_row_order":
            rows = (dict(reversed(tuple(rows[0].items()))), rows[1])
        elif defect == "numeric_value":
            rows[0]["Value"] = 603
        elif defect in {"null_technical", "empty_technical", "blank_technical"}:
            rows[0]["Library Ref"] = {"null_technical": None, "empty_technical": "", "blank_technical": " \t "}[defect]
        elif defect in {"duplicate_ipn", "case_ipn_collision"}:
            rows[1]["IPN"] = rows[0]["IPN"].lower() if defect == "case_ipn_collision" else rows[0]["IPN"]
        snapshot = PreparedTables((replace(table, columns=columns, rows=rows),))
    destination = tmp_path / "not created" / "components.sqlite"
    with pytest.raises(ExportValidationError):
        writer.write_sqlite_database(snapshot, destination)
    assert not destination.parent.exists()


def test_full_rebuild_removes_old_tables_rows_and_columns(prepared, tmp_path):
    destination = tmp_path / "output" / "components.sqlite"
    writer.write_sqlite_database(prepared, destination)
    first = prepared.tables[0]
    columns = tuple(c for c in first.columns if c.name != "Package")
    rows = ({name: value for name, value in first.rows[1].items() if name != "Package"},)
    snapshot = one_table(prepared, name="Renamed Resistors", columns=columns, rows=rows)
    writer.write_sqlite_database(snapshot, destination)
    with closing(sqlite3.connect(destination)) as connection:
        assert connection.execute("SELECT name FROM sqlite_schema WHERE type='table'").fetchall() == [("Renamed Resistors",)]
        assert connection.execute('SELECT "IPN" FROM "Renamed Resistors"').fetchall() == [(rows[0]["IPN"],)]
        assert "Package" not in [r[1] for r in connection.execute('PRAGMA table_info("Renamed Resistors")')]
    writer._verify_database(snapshot, destination.resolve())


@pytest.mark.parametrize("step", ["create", "insert", "commit", "verify", "replace"])
def test_failures_preserve_published_database_and_clean_owned_files(prepared, tmp_path, monkeypatch, step):
    destination = tmp_path / "output" / "components.sqlite"
    writer.write_sqlite_database(prepared, destination)
    before = destination.read_bytes()
    unrelated = destination.parent / ".someone-else.staging.sqlite"
    unrelated.write_bytes(b"belongs to another operation")
    if step in {"create", "insert", "commit"}:
        real_connect = sqlite3.connect

        class FailingConnection(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                if step == "create" and sql.startswith("CREATE TABLE"):
                    raise sqlite3.OperationalError("simulated creation failure")
                return super().execute(sql, *args, **kwargs)

            def executemany(self, sql, values):
                if step == "insert":
                    super().executemany(sql, [next(iter(values))])
                    raise sqlite3.OperationalError("simulated disk insertion failure")
                return super().executemany(sql, values)

            def __exit__(self, *args):
                if step == "commit" and args[0] is None:
                    self.rollback()
                    raise sqlite3.OperationalError("simulated commit failure")
                return super().__exit__(*args)

        def connect(database, *args, **kwargs):
            if database != ":memory:" and not kwargs.get("uri"):
                kwargs["factory"] = FailingConnection
            return real_connect(database, *args, **kwargs)
        monkeypatch.setattr(writer.sqlite3, "connect", connect)
    elif step == "verify":
        monkeypatch.setattr(writer, "_verify_database", Mock(side_effect=writer.DatabaseError("simulated verification failure")))
    else:
        monkeypatch.setattr(writer.os, "replace", Mock(side_effect=PermissionError("database held open by another process")))
    with pytest.raises(writer.DatabaseError):
        writer.write_sqlite_database(prepared, destination)
    assert destination.read_bytes() == before
    assert unrelated.read_bytes() == b"belongs to another operation"
    assert set(p.name for p in destination.parent.iterdir()) == {destination.name, unrelated.name}


def test_reopen_is_read_only_and_after_writer_closed(prepared, tmp_path, monkeypatch):
    destination = tmp_path / "output" / "components.sqlite"
    original = writer._verify_database
    observed = []

    def verify(snapshot, staging):
        # Renaming the file on Windows requires the writer's handle to be closed.
        renamed = staging.with_suffix(".probe")
        staging.rename(renamed)
        renamed.rename(staging)
        assert staging.parent == destination.parent
        assert staging != destination
        observed.append(staging)
        original(snapshot, staging)
    real_connect = sqlite3.connect

    def connect(database, *args, **kwargs):
        if kwargs.get("uri"):
            assert str(database).endswith("?mode=ro")
        return real_connect(database, *args, **kwargs)
    monkeypatch.setattr(writer, "_verify_database", verify)
    monkeypatch.setattr(writer.sqlite3, "connect", connect)
    writer.write_sqlite_database(prepared, destination)
    assert len(observed) == 1 and not observed[0].exists()


@pytest.mark.parametrize("corruption", ["extra_table", "missing_table", "value", "null", "count", "ipn", "type", "notnull", "collation", "column_order", "trigger", "integrity"])
def test_verification_detects_corruption_before_publication(prepared, tmp_path, monkeypatch, corruption):
    destination = tmp_path / "output" / "components.sqlite"
    writer.write_sqlite_database(prepared, destination)
    before = destination.read_bytes()
    original = writer._write_staging

    def corrupt(snapshot, staging):
        original(snapshot, staging)
        if corruption == "integrity":
            staging.write_bytes(b"not a SQLite database")
            return
        with closing(sqlite3.connect(staging)) as connection, connection:
            if corruption == "extra_table":
                connection.execute('CREATE TABLE "Unwanted" ("Extra" TEXT)')
            elif corruption == "missing_table":
                connection.execute('DROP TABLE "Resistors"')
            elif corruption in {"value", "null", "ipn"}:
                field = {"value": "Value", "null": "Package", "ipn": "IPN"}[corruption]
                connection.execute(f'UPDATE "Resistors" SET {writer.quote_identifier(field)} = ? WHERE "IPN" = ?', ("wrong", snapshot.tables[0].rows[0]["IPN"]))
            elif corruption == "count":
                connection.execute('DELETE FROM "Resistors"')
            elif corruption == "trigger":
                connection.execute('CREATE TRIGGER "Extra" AFTER INSERT ON "Resistors" BEGIN SELECT 1; END')
            else:
                connection.execute('ALTER TABLE "Resistors" RENAME TO "Old"')
                declarations = []
                columns = tuple(reversed(snapshot.tables[0].columns)) if corruption == "column_order" else snapshot.tables[0].columns
                for c in columns:
                    sql_type = "BLOB" if corruption == "type" and c.name == "Value" else "TEXT"
                    constraint = " NOT NULL" if c.template_pk is None and not (corruption == "notnull" and c.name == "Library Ref") else ""
                    if c.name == "IPN":
                        constraint += " PRIMARY KEY COLLATE " + ("BINARY" if corruption == "collation" else "NOCASE")
                    declarations.append(f"{writer.quote_identifier(c.name)} {sql_type}{constraint}")
                connection.execute(f'CREATE TABLE "Resistors" ({", ".join(declarations)})')
                connection.execute('DROP TABLE "Old"')
    monkeypatch.setattr(writer, "_write_staging", corrupt)
    with pytest.raises(writer.DatabaseError):
        writer.write_sqlite_database(prepared, destination)
    assert destination.read_bytes() == before
    assert [p.name for p in destination.parent.iterdir()] == [destination.name]


def test_conflicting_lock_is_never_removed(prepared, tmp_path):
    destination = tmp_path / "output" / "components.sqlite"
    writer.write_sqlite_database(prepared, destination)
    before = destination.read_bytes()
    lock = destination.parent / "components.sqlite.sync.lock"
    lock.write_text("pid=potentially-interrupted-owner\n", encoding="ascii")
    with pytest.raises(writer.DatabaseError, match="Synchronization lock exists.*manual recovery"):
        writer.write_sqlite_database(prepared, destination)
    assert destination.read_bytes() == before
    assert lock.read_text(encoding="ascii") == "pid=potentially-interrupted-owner\n"
    assert set(p.name for p in destination.parent.iterdir()) == {destination.name, lock.name}


def test_nested_writer_cannot_acquire_destination_lock(prepared, tmp_path, monkeypatch):
    destination = tmp_path / "output" / "components.sqlite"
    original = writer._write_staging

    def nested(snapshot, staging):
        with pytest.raises(writer.DatabaseError, match="lock exists"):
            writer.write_sqlite_database(snapshot, destination)
        original(snapshot, staging)
    monkeypatch.setattr(writer, "_write_staging", nested)
    writer.write_sqlite_database(prepared, destination)
    assert [p.name for p in destination.parent.iterdir()] == [destination.name]


def test_schema_limit_is_a_validation_error(prepared):
    with closing(sqlite3.connect(":memory:")) as connection:
        limit = connection.getlimit(sqlite3.SQLITE_LIMIT_COLUMN)
    columns = TECHNICAL_COLUMNS + tuple(ColumnDefinition(f"Field {pk}", pk) for pk in range(1, limit))
    row = {column.name: "text" for column in columns}
    with pytest.raises(ExportValidationError, match="SQLite schema/data compatibility"):
        writer.validate_sqlite_tables(one_table(prepared, columns=columns, rows=(row,)))


def test_memory_validation_creates_no_files(prepared, tmp_path, monkeypatch):
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.chdir(working)
    writer.validate_sqlite_tables(prepared)
    assert not list(working.iterdir())


def test_new_parts_parameters_and_categories_replace_current_snapshot(prepared, tmp_path):
    destination = tmp_path / "output" / "components.sqlite"
    writer.write_sqlite_database(prepared, destination)
    table = prepared.tables[0]
    columns = (*table.columns, ColumnDefinition("Comment", 101))
    rows = tuple({**row, "Comment": "explicit InvenTree parameter"} for row in table.rows)
    added = {**rows[0], "IPN": "RES-NEW-PART"}
    updated = replace(table, columns=columns, rows=(*rows, added))
    moved = replace(updated, category_pk=4, name="Connectors", rows=(rows[1],))
    current = PreparedTables((replace(updated, rows=(rows[0], added)), moved))
    writer.write_sqlite_database(current, destination)
    writer._verify_database(current, destination.resolve())
    # Resistors becomes empty: it is omitted by preparation and disappears.
    writer.write_sqlite_database(PreparedTables((moved,)), destination)
    with closing(sqlite3.connect(destination)) as connection:
        assert connection.execute("SELECT name FROM sqlite_schema WHERE type='table'").fetchall() == [("Connectors",)]
        assert connection.execute('SELECT "IPN", "Comment" FROM "Connectors"').fetchall() == [(rows[1]["IPN"], "explicit InvenTree parameter")]


def test_integrity_check_must_report_ok(prepared):
    connection = Mock()
    connection.execute.return_value.fetchall.return_value = [("simulated corruption",)]
    with pytest.raises(writer.DatabaseError, match="integrity_check failed"):
        writer._verify_connection(connection, prepared)


def test_staging_creation_failure_releases_own_lock(prepared, tmp_path, monkeypatch):
    destination = tmp_path / "output" / "components.sqlite"
    writer.write_sqlite_database(prepared, destination)
    before = destination.read_bytes()
    monkeypatch.setattr(writer.tempfile, "mkstemp", Mock(side_effect=OSError("disk full")))
    with pytest.raises(writer.DatabaseError, match="disk full"):
        writer.write_sqlite_database(prepared, destination)
    assert destination.read_bytes() == before
    assert [p.name for p in destination.parent.iterdir()] == [destination.name]
