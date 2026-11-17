import ast
from pathlib import Path
import subprocess
import tomllib

import pytest

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parents[1]


def test_independent_runtime_has_no_external_dependencies():
    config = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["dependencies"] == []
    for path in (PROJECT / "src").rglob("*.py"):
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith(("inventree_sync", "subprocess", "requests", "pyodbc")) for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(("inventree_sync", "subprocess", "requests", "pyodbc"))


def test_dblib_portable_connection_preserved():
    data = (ROOT / "database/Components.DbLib").read_bytes()
    assert [line for line in data.splitlines() if line.startswith(b"ConnectionString=")] == [
        b'ConnectionString=Provider=MSDASQL.1;Persist Security Info=False;Extended Properties="DSN=AltiumComponents;"']
    assert data.count(b"\n") == data.count(b"\r\n")
    assert b"Database=" not in data and b"Driver=" not in data


@pytest.mark.parametrize("path,ignored", [
    ("tools/setup-odbc.exe", False), ("tools/inventree-sync.exe", False),
    ("tools/setup-odbc/.venv/pyvenv.cfg", True), ("tools/setup-odbc/build/candidate-x/setup-odbc.exe", True),
    ("tools/setup-odbc/dist/setup-odbc.exe", True), ("tools/setup-odbc/tests/__pycache__/test.pyc", True),
    ("tools/setup-odbc/tests/disposable.sqlite", True),
])
def test_ignore_rules(path, ignored):
    if not (ROOT / ".git").exists():
        pytest.skip("Source archive without Git metadata")
    result = subprocess.run(["git", "check-ignore", "--no-index", "-q", path], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode in (0, 1), result.stderr
    assert (result.returncode == 0) == ignored
