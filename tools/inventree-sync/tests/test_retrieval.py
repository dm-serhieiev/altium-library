from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qsl, urlsplit

import pytest
import requests

from inventree_sync.adapters import AdapterError
from inventree_sync.api import APIError
from inventree_sync.categories import CategoryError
from inventree_sync.cli import main
from inventree_sync.retrieval import DatasetError, retrieve_dataset

EXAMPLE = Path(__file__).parents[1] / "config.example.toml"
CATEGORIES = [
    {"pk": 1, "name": "Electronic Components", "parent": None},
    {"pk": 2, "name": "Resistors", "parent": 1},
    {"pk": 3, "name": "Empty Leaf", "parent": 1},
    {"pk": 9, "name": "Outside", "parent": None},
]


def response(payload, status=200):
    result = Mock(status_code=status, headers={})
    result.json.return_value = payload
    return result


@pytest.fixture
def scoped_transport(monkeypatch, runtime_token, runtime_auth):
    monkeypatch.setattr("builtins.input", lambda prompt: runtime_auth.username)
    monkeypatch.setattr("inventree_sync.cli.getpass.getpass", lambda prompt: runtime_auth.password)
    session = Mock()
    monkeypatch.setattr(requests, "Session", Mock(return_value=session))
    return session


def two_parts(fixture_record):
    first = fixture_record("part_with_parameters")
    second = deepcopy(first)
    second.update(pk=21, IPN="RES-1K-1%-0603")
    second["parameters"][0].update(pk=41, model_id=21)
    return first, second


def test_paginated_dataset_uses_only_two_resources(scoped_transport, fixture_record, runtime_auth):
    first, second = two_parts(fixture_record)
    scoped_transport.get.side_effect = [
        response({"count": 4, "results": CATEGORIES[:2], "next": "?offset=2"}),
        response({"count": 4, "results": CATEGORIES[2:], "next": None}),
        response({"count": 2, "results": [first], "next": "?category=1&cascade=true&parameters=true&offset=1"}),
        response({"count": 2, "results": [second], "next": None}),
    ]
    dataset = retrieve_dataset(EXAMPLE, auth=runtime_auth)
    assert dataset.root_category_pk == 1
    assert dataset.scope_category_pks == {1, 2, 3}
    assert set(dataset.tree.categories) == {1, 2, 3, 9}
    assert set(dataset.parts) == {20, 21}
    assert set(dataset.templates) == {30}
    assert dataset.templates[30].name == "Package"
    assert dataset.templates[30].units == ""
    assert dataset.parameters[20][30].data == "0603"
    assert dataset.parameters[21][30].pk == 41
    assert dataset.groups == {2: (dataset.parts[20], dataset.parts[21])}
    assert scoped_transport.get.call_count == 4  # C=2 + P=2, not per Part/template
    paths = [urlsplit(call.args[0]).path for call in scoped_transport.get.call_args_list]
    assert paths == ["/api/part/category/"] * 2 + ["/api/part/"] * 2
    scoped_transport.close.assert_called_once()
    with pytest.raises(TypeError):
        dataset.templates[1] = dataset.templates[30]
    with pytest.raises(TypeError):
        dataset.parameters[20][31] = dataset.parameters[20][30]


def test_zero_parameters_and_different_parameter_sets(scoped_transport, fixture_record, runtime_auth):
    first, second = two_parts(fixture_record)
    second["parameters"] = []
    extra = deepcopy(first["parameters"][0])
    extra.update(pk=42, template=31, data="10 kΩ", template_detail={"pk": 31, "name": "Resistance", "units": "Ω"})
    first["parameters"].append(extra)
    scoped_transport.get.side_effect = [response(CATEGORIES), response([first, second])]
    dataset = retrieve_dataset(EXAMPLE, auth=runtime_auth)
    assert set(dataset.parameters[20]) == {30, 31}
    assert not dataset.parameters[21]
    assert set(dataset.templates) == {30, 31}


def test_nested_scope_resolves_its_actual_pk(scoped_transport, fixture_record, tmp_path, runtime_auth):
    config = tmp_path / "config.toml"
    config.write_text(
        EXAMPLE.read_text(encoding="utf-8").replace(
            'root_category_path = ["Electronic Components"]',
            'root_category_path = ["Electronic Components", "Passives"]',
        ),
        encoding="utf-8",
    )
    categories = [
        CATEGORIES[0],
        {"pk": 10, "name": "Passives", "parent": 1},
        {**CATEGORIES[1], "parent": 10},
        CATEGORIES[2],
        CATEGORIES[3],
    ]
    scoped_transport.get.side_effect = [response(categories), response([fixture_record("part_with_parameters")])]
    dataset = retrieve_dataset(config, auth=runtime_auth)
    assert dataset.root_category_pk == 10
    assert dataset.scope_category_pks == {10, 2}
    assert set(dataset.tree.categories) == {1, 10, 2, 3, 9}
    assert dict(parse_qsl(urlsplit(scoped_transport.get.call_args.args[0]).query)) == {
        "category": "10", "cascade": "true", "parameters": "true",
    }


def test_dataset_with_no_parameters_is_valid(scoped_transport, fixture_record, runtime_auth):
    record = fixture_record("part_with_parameters")
    record["parameters"] = []
    scoped_transport.get.side_effect = [response(CATEGORIES), response([record])]
    dataset = retrieve_dataset(EXAMPLE, auth=runtime_auth)
    assert set(dataset.parts) == {20}
    assert dataset.parameters == {20: {}}
    assert dataset.templates == {}
    assert set(dataset.groups) == {2}


@pytest.mark.parametrize("field,value", [("name", "Different Name"), ("units", "V")])
def test_conflicting_shared_template(scoped_transport, fixture_record, field, value, runtime_auth):
    first, second = two_parts(fixture_record)
    second["parameters"][0]["template_detail"][field] = value
    scoped_transport.get.side_effect = [response(CATEGORIES), response([first, second])]
    with pytest.raises(DatasetError, match="conflicting metadata") as error:
        retrieve_dataset(EXAMPLE, auth=runtime_auth)
    assert all(text in str(error.value) for text in ("Part pk=20", "Part pk=21", "template pk=30"))
    scoped_transport.close.assert_called_once()


def test_duplicate_parameter_pk_across_parts(scoped_transport, fixture_record, runtime_auth):
    first, second = two_parts(fixture_record)
    second["parameters"][0]["pk"] = 40
    scoped_transport.get.side_effect = [response(CATEGORIES), response([first, second])]
    with pytest.raises(DatasetError, match="duplicate parameter pk=40"):
        retrieve_dataset(EXAMPLE, auth=runtime_auth)


@pytest.mark.parametrize("category,match", [(1, "non-leaf"), (9, "outside selected scope"), (None, "missing/unknown"), (999, "missing/unknown")])
def test_server_part_placement_is_checked(scoped_transport, fixture_record, category, match, runtime_auth):
    record = fixture_record("part_with_parameters")
    record["category"] = category
    scoped_transport.get.side_effect = [response(CATEGORIES), response([record])]
    with pytest.raises(CategoryError, match=match):
        retrieve_dataset(EXAMPLE, auth=runtime_auth)
    scoped_transport.close.assert_called_once()


def test_duplicate_ipns_are_rejected(scoped_transport, fixture_record, runtime_auth):
    first, second = two_parts(fixture_record)
    second["IPN"] = first["IPN"].lower()
    scoped_transport.get.side_effect = [response(CATEGORIES), response([first, second])]
    with pytest.raises(CategoryError, match="duplicate IPN"):
        retrieve_dataset(EXAMPLE, auth=runtime_auth)


def test_no_exported_parts(scoped_transport, runtime_auth):
    scoped_transport.get.side_effect = [response(CATEGORIES), response([])]
    with pytest.raises(CategoryError, match="no exported Parts"):
        retrieve_dataset(EXAMPLE, auth=runtime_auth)


@pytest.mark.parametrize("categories", [[], [CATEGORIES[0], {**CATEGORIES[0], "pk": 11}]])
def test_unresolved_root_does_not_request_parts(scoped_transport, categories, runtime_auth):
    scoped_transport.get.return_value = response(categories)
    with pytest.raises(CategoryError, match="expected exactly one"):
        retrieve_dataset(EXAMPLE, auth=runtime_auth)
    assert scoped_transport.get.call_count == 1


@pytest.mark.parametrize("defect", ["parameters", "template_detail", "units"])
def test_missing_nested_data_never_falls_back(scoped_transport, fixture_record, defect, runtime_auth):
    record = fixture_record("part_with_parameters")
    if defect == "parameters":
        del record[defect]
    elif defect == "template_detail":
        del record["parameters"][0][defect]
    else:
        del record["parameters"][0]["template_detail"][defect]
    scoped_transport.get.side_effect = [response(CATEGORIES), response([record])]
    with pytest.raises(AdapterError):
        retrieve_dataset(EXAMPLE, auth=runtime_auth)
    assert scoped_transport.get.call_count == 2
    scoped_transport.close.assert_called_once()


def test_inspect_runs_actual_workflow(scoped_transport, fixture_record, runtime_token, capsys, runtime_auth):
    first, second = two_parts(fixture_record)
    scoped_transport.get.side_effect = [response(CATEGORIES), response([first, second])]
    assert main(["inspect", "--config", str(EXAMPLE)]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    for expected in ("Electronic Components", "PK 1", "Categories in subtree: 3", "Parts retrieved: 2", "Exported leaf categories: 1", "Part parameters: 2", "Distinct ParameterTemplates: 1", "Nested parameter retrieval: used"):
        assert expected in output.out
    assert runtime_token not in output.out
    assert "Authorization" not in output.out
    assert "RES-10K" not in output.out
    assert dict(parse_qsl(urlsplit(scoped_transport.get.call_args.args[0]).query)) == {"category": "1", "cascade": "true", "parameters": "true"}


@pytest.mark.parametrize("status", [401, 403])
def test_inspect_authentication_failure(scoped_transport, status, capsys, runtime_auth):
    scoped_transport.get.return_value = response(None, status)
    assert main(["inspect", "--config", str(EXAMPLE)]) == 3
    output = capsys.readouterr()
    assert "successful" not in output.out.lower() and str(status) in output.err
    assert scoped_transport.get.call_count == 1
    scoped_transport.close.assert_called_once()


def test_inspect_pagination_failure(scoped_transport, fixture_record, capsys, runtime_auth):
    scoped_transport.get.side_effect = [
        response(CATEGORIES),
        response({"results": [fixture_record("part_with_parameters")], "next": "?offset=1"}),
    ]
    assert main(["inspect", "--config", str(EXAMPLE)]) == 3
    output = capsys.readouterr()
    assert "successful" not in output.out.lower() and "pagination URL" in output.err
    assert scoped_transport.get.call_count == 2


def test_inspect_no_parts_fails(scoped_transport, capsys, runtime_auth):
    scoped_transport.get.side_effect = [response(CATEGORIES), response([])]
    assert main(["inspect", "--config", str(EXAMPLE)]) == 2
    assert "no exported Parts" in capsys.readouterr().err


def test_inspect_malformed_response_is_error(scoped_transport, fixture_record, capsys, runtime_auth):
    scoped_transport.get.side_effect = [response(CATEGORIES), response([fixture_record("part")])]
    assert main(["inspect", "--config", str(EXAMPLE)]) == 3
    output = capsys.readouterr()
    assert "successful" not in output.out.lower() and "parameters" in output.err


def test_inspect_does_not_expose_unexpected_error(scoped_transport, runtime_token, capsys, runtime_auth):
    scoped_transport.get.side_effect = RuntimeError(runtime_token)
    assert main(["inspect", "--config", str(EXAMPLE)]) == 1
    output = capsys.readouterr()
    assert runtime_token not in output.err
    assert "successful" not in output.out.lower()
