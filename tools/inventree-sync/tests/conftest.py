import json
from pathlib import Path
from types import MappingProxyType
from uuid import uuid4

import pytest
import requests

from inventree_sync.categories import build_category_tree, group_parts
from inventree_sync.models import Category, Parameter, ParameterTemplate, Part
from inventree_sync.retrieval import PreparedDataset
from inventree_sync.transform import LibraryLayout


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Unit tests must not access a live server")
    monkeypatch.setattr(requests.sessions.Session, "request", fail)


@pytest.fixture
def runtime_token(monkeypatch):
    # Ephemeral synthetic value: no credentials are checked into fixtures.
    value = uuid4().hex
    monkeypatch.setenv("INVENTREE_API_TOKEN", value)
    return value


@pytest.fixture
def fixture_record():
    def read(name):
        return json.loads((Path(__file__).parent / "fixtures" / f"{name}.json").read_text(encoding="utf-8"))
    return read


@pytest.fixture
def export_dataset():
    """Small typed 1B dataset; these are test data, not runtime category profiles."""
    tree = build_category_tree([
        Category(1, "Components", None), Category(2, "Resistors", 1),
        Category(3, "Empty Leaf", 1), Category(4, "Connectors", 1),
    ])
    parts = {20: Part(20, "RES-10K-1%-0603", 2), 21: Part(21, "RES-1K-1%-0603", 2)}
    templates = {pk: ParameterTemplate(pk, name, "") for pk, name in (
        (10, "Altium Symbol"), (11, "Altium Footprint"),
        (12, "KiCad Symbol"), (13, "KiCad Footprint"), (30, "Value"),
        (31, "Package"), (35, "Power Rating"), (99, "Unused Template"),
    )}
    templates[35] = ParameterTemplate(35, "Power Rating", "W")
    parameters = {
        20: {
            10: Parameter(100, 20, 10, "Passives:Resistor"),
            11: Parameter(101, 20, 11, "Resistors:RES_0603_H0.55"),
            12: Parameter(108, 20, 12, "Device:R"),
            13: Parameter(109, 20, 13, "Resistor_SMD:R_0603_1608Metric"),
            30: Parameter(102, 20, 30, "10 kΩ"),
            31: Parameter(103, 20, 31, "0603"),
        },
        21: {
            10: Parameter(104, 21, 10, "Passives.SchLib:Resistor"),
            11: Parameter(105, 21, 11, "Resistors.PcbLib:RES_0603_H0.55"),
            30: Parameter(106, 21, 30, "1 kΩ"),
            35: Parameter(107, 21, 35, "0.125"),
        },
    }
    return PreparedDataset(
        tree, 1, tree.subtree(1), MappingProxyType(parts),
        MappingProxyType({pk: MappingProxyType(values) for pk, values in parameters.items()}),
        MappingProxyType(templates), MappingProxyType(group_parts(parts.values(), tree, 1)),
    )


@pytest.fixture
def library_layout(tmp_path):
    symbols = tmp_path / "symbols"
    footprints = tmp_path / "footprints"
    symbols.mkdir()
    footprints.mkdir()
    for directory, filename in ((symbols, "Passives.SchLib"), (footprints, "Resistors.PcbLib")):
        (directory / filename).write_bytes(b"dummy library for file-existence tests only")
    return LibraryLayout(tmp_path / "database" / "Components.DbLib", symbols, footprints)


@pytest.fixture
def export_config(tmp_path, library_layout, runtime_token):
    path = tmp_path / "settings" / "config.toml"
    path.parent.mkdir()
    path.write_text(
        '[inventree]\nbase_url = "https://inventree.example.com"\n'
        '[scope]\nroot_category_path = ["Components"]\n'
        '[sync]\noutput = "../database/components.sqlite"\ndblib = "../database/Components.DbLib"\n'
        '[libraries]\nsymbols = "../symbols"\nfootprints = "../footprints"\n',
        encoding="utf-8",
    )
    return path

