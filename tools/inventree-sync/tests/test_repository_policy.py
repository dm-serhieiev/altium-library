from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize("path,ignored", [
    ("database/components.sqlite", False),
    ("database/other.sqlite", True),
    ("database/other.SQLITE3", True),
    ("elsewhere/components.sqlite", True),
    ("database/components.sqlite-wal", True),
    ("database/components.sqlite-shm", True),
    ("database/components.sqlite-journal", True),
    ("database/components.sqlite.sync.lock", True),
    ("database/unique.staging.sqlite", True),
    ("database/unique.staging.sqlite-journal", True),
    ("tools/config.toml", True),
    ("tools/config.example.toml", False),
    ("tools/inventree-sync.exe", False),
    ("tools/unrelated.exe", True),
    ("tools/inventree-sync/.venv/pyvenv.cfg", True),
    ("tools/inventree-sync/tests/fixtures/example.sql", False),
])
def test_gitignore_snapshot_exception(path, ignored):
    root = Path(__file__).resolve().parents[3]
    if not (root / ".git").exists():
        pytest.skip("Source archive has no Git working tree")
    result = subprocess.run(["git", "check-ignore", "--no-index", "-q", path], cwd=root, capture_output=True, text=True)
    assert result.returncode in (0, 1), result.stderr
    assert (result.returncode == 0) == ignored
