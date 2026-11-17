"""Only disposable SQLite files and uniquely named User DSNs are mutated."""

import shutil
from uuid import uuid4

import pytest

from setup_odbc.database import snapshot
from setup_odbc.drivers import DEFAULT_DRIVER, installed_drivers, select_driver
from setup_odbc.dsn import Installer, configure, read_dsn
from setup_odbc.errors import SetupError
from setup_odbc.odbc import connect_readonly


@pytest.mark.integration
def test_real_create_repeat_move_check_rollback_readonly_and_no_create(snapshot_path, tmp_path):
    drivers = installed_drivers()
    if not any(d.name.casefold() == DEFAULT_DRIVER.casefold() and d.bits == 64 for d in drivers):
        pytest.skip("SQLite3 x64 ODBC driver is not installed")
    driver = select_driver(DEFAULT_DRIVER, drivers)
    name = "AltiumTest-" + uuid4().hex[:16]
    assert read_dsn(name, driver) is None
    moved = tmp_path / "Moved Україна space % #.sqlite"
    corrupt = tmp_path / "Corrupt.sqlite"
    shutil.copyfile(snapshot_path, moved)
    data = bytearray(snapshot_path.read_bytes())
    data[100] = 255
    corrupt.write_bytes(data)
    files = (snapshot_path, moved, corrupt)
    before = {p: p.read_bytes() for p in files}
    try:
        with snapshot(snapshot_path):
            assert configure(name, driver, snapshot_path) == "New User DSN created."
            original = read_dsn(name, driver)
            assert configure(name, driver, snapshot_path) == "Already configured. No changes required."
            assert read_dsn(name, driver) == original
        with snapshot(moved):
            assert configure(name, driver, moved) == "Existing DSN updated."
            configure(name, driver, moved, check_only=True)
            prior = read_dsn(name, driver)
            assert prior.attributes["nocreat"] == "1"
            with connect_readonly(name, moved) as connection:
                with pytest.raises(SetupError, match="connection failure"):
                    connection.query("INSERT INTO parts VALUES ('MUST-NOT-BE-WRITTEN')", 0)
        with snapshot(corrupt), pytest.raises(SetupError, match="Previous DSN database setting restored"):
            configure(name, driver, corrupt)
        assert read_dsn(name, driver) == prior
        # The read guard itself must not be the only reason INSERT was rejected.
        # This disposable file is immutable and has no other users or journals.
        with connect_readonly(name, moved) as connection:
            with pytest.raises(SetupError, match="connection failure"):
                connection.query("INSERT INTO parts VALUES ('MUST-NOT-BE-WRITTEN')", 0)
        missing = tmp_path / "must-not-be-created.sqlite"
        with pytest.raises(SetupError, match="connection failure"), connect_readonly(name, missing):
            pytest.fail("Missing database was opened")
        assert not missing.exists()
        # Exercise restoration of original attribute absence through native APIs.
        Installer().database(name, None)
        no_database = read_dsn(name, driver)
        assert "database" not in no_database.attributes
        with snapshot(corrupt), pytest.raises(SetupError, match="restored"):
            configure(name, driver, corrupt)
        assert read_dsn(name, driver) == no_database
    finally:
        # The only name ever used here is the unique test-owned name above.
        if read_dsn(name, driver) is not None:
            Installer().remove(name, driver)
        assert read_dsn(name, driver) is None
        assert {p: p.read_bytes() for p in files} == before
        for p in files:
            assert not any(p.with_name(p.name + suffix).exists() for suffix in ("-journal", "-wal", "-shm"))
