import json
from pathlib import Path
from uuid import uuid4

import pytest
import requests


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

