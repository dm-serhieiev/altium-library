import pytest

from inventree_sync import adapters
from inventree_sync.models import Category, Parameter, ParameterTemplate, Part


@pytest.mark.parametrize("fixture,adapter,expected", [
    ("category", adapters.category, Category(1, "Components", None)),
    ("part", adapters.part, Part(20, "RES-10K-1%-0603", 2)),
    ("template", adapters.parameter_template, ParameterTemplate(30, "Package")),
    ("parameter", adapters.parameter, Parameter(40, 20, 30, "0603")),
])
def test_valid_records(fixture_record, fixture, adapter, expected):
    assert adapter(fixture_record(fixture)) == expected


@pytest.mark.parametrize("fixture,adapter,fields", [
    ("category", adapters.category, ("pk", "name", "parent")),
    ("part", adapters.part, ("pk", "IPN", "category")),
    ("template", adapters.parameter_template, ("pk", "name")),
    ("parameter", adapters.parameter, ("pk", "model_type", "model_id", "template", "data")),
])
def test_required_fields(fixture_record, fixture, adapter, fields):
    for field in fields:
        raw = fixture_record(fixture)
        del raw[field]
        with pytest.raises(adapters.AdapterError, match=field):
            adapter(raw)


@pytest.mark.parametrize("raw", [None, [], "record", 3])
@pytest.mark.parametrize("adapter", [adapters.category, adapters.part, adapters.parameter_template, adapters.parameter])
def test_non_objects(adapter, raw):
    with pytest.raises(adapters.AdapterError, match="object"):
        adapter(raw)


@pytest.mark.parametrize("value", [True, 0, -1, "1", {}, 1.0])
def test_invalid_pk(fixture_record, value):
    raw = fixture_record("category")
    raw["pk"] = value
    with pytest.raises(adapters.AdapterError, match="positive integer"):
        adapters.category(raw)


@pytest.mark.parametrize("value", ["0603", "1%", "1E3", "10 kΩ", "=example", "  text  ", "0", "None", "NaN"])
def test_text_preserved(fixture_record, value):
    raw = fixture_record("parameter")
    raw.update(data=value, data_numeric=603)
    assert adapters.parameter(raw).data == value


@pytest.mark.parametrize("value", [None, ""])
def test_missing_value(fixture_record, value):
    raw = fixture_record("parameter")
    raw["data"] = value
    assert adapters.parameter(raw).data is None


@pytest.mark.parametrize("value", [603, 1.5, False, [], {}])
def test_no_numeric_coercion(fixture_record, value):
    raw = fixture_record("parameter")
    raw["data"] = value
    with pytest.raises(adapters.AdapterError, match="Part pk=20 template pk=30"):
        adapters.parameter(raw)


@pytest.mark.parametrize("model_type", ["part", "stock.stockitem", None, 10])
def test_unsupported_model_type(fixture_record, model_type):
    raw = fixture_record("parameter")
    raw["model_type"] = model_type
    with pytest.raises(adapters.AdapterError, match="model_type"):
        adapters.parameter(raw)


def test_part_nulls_not_fabricated(fixture_record):
    raw = fixture_record("part")
    raw.update(IPN=None, category=None, name="Not an IPN")
    assert adapters.part(raw) == Part(20, None, None)

