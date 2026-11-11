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


def test_nested_part_is_typed(fixture_record):
    result = adapters.part_with_parameters(fixture_record("part_with_parameters"))
    assert result.pk == 20
    assert result.part == Part(20, "RES-10K-1%-0603", 2)
    assert result.parameters == (Parameter(40, 20, 30, "0603"),)
    assert result.templates == (ParameterTemplate(30, "Package", ""),)


def test_empty_nested_parameters_are_valid(fixture_record):
    raw = fixture_record("part_with_parameters")
    raw["parameters"] = []
    result = adapters.part_with_parameters(raw)
    assert result.parameters == () and result.templates == ()


def test_missing_nested_parameters_is_error(fixture_record):
    raw = fixture_record("part")
    with pytest.raises(adapters.AdapterError, match="Part pk=20.*parameters"):
        adapters.part_with_parameters(raw)


@pytest.mark.parametrize("records", [None, {}, "", 4, [None], ["bad"], [[]]])
def test_malformed_nested_parameters(fixture_record, records):
    raw = fixture_record("part_with_parameters")
    raw["parameters"] = records
    with pytest.raises(adapters.AdapterError, match="Part pk=20"):
        adapters.part_with_parameters(raw)


@pytest.mark.parametrize("field", ["pk", "model_id", "template", "data", "template_detail"])
def test_missing_nested_parameter_field(fixture_record, field):
    raw = fixture_record("part_with_parameters")
    del raw["parameters"][0][field]
    with pytest.raises(adapters.AdapterError, match=f"Part pk=20.*{field}"):
        adapters.part_with_parameters(raw)


@pytest.mark.parametrize("field,value", [
    ("pk", True), ("pk", 0), ("pk", "40"),
    ("model_id", 99), ("model_id", None), ("model_id", "20"),
    ("template", 0), ("template", True), ("template", {}),
    ("model_type", "stock.stockitem"), ("model_type", None),
    ("template_detail", None), ("template_detail", []),
    ("data", 603), ("data", False),
])
def test_invalid_nested_parameter(fixture_record, field, value):
    raw = fixture_record("part_with_parameters")
    raw["parameters"][0][field] = value
    with pytest.raises(adapters.AdapterError, match="Part pk=20"):
        adapters.part_with_parameters(raw)


def test_nested_model_type_checked_when_present(fixture_record):
    raw = fixture_record("part_with_parameters")
    del raw["parameters"][0]["model_type"]
    assert adapters.part_with_parameters(raw).parameters[0].part_pk == 20


@pytest.mark.parametrize("field", ["pk", "name", "units"])
def test_missing_template_detail_field(fixture_record, field):
    raw = fixture_record("part_with_parameters")
    del raw["parameters"][0]["template_detail"][field]
    with pytest.raises(adapters.AdapterError, match="Part pk=20") as error:
        adapters.part_with_parameters(raw)
    assert field in str(error.value)


@pytest.mark.parametrize("field,value", [("pk", 31), ("pk", False), ("name", None), ("name", 10), ("units", None), ("units", ["V"])])
def test_invalid_template_detail(fixture_record, field, value):
    raw = fixture_record("part_with_parameters")
    raw["parameters"][0]["template_detail"][field] = value
    with pytest.raises(adapters.AdapterError, match="Part pk=20"):
        adapters.part_with_parameters(raw)


@pytest.mark.parametrize("value", ["0603", "1%", "1E3", "10 kΩ", "=example", "  spaced  ", "", None])
def test_nested_text_preserved(fixture_record, value):
    raw = fixture_record("part_with_parameters")
    raw["parameters"][0].update(data=value, data_numeric=603)
    assert adapters.part_with_parameters(raw).parameters[0].data == (None if value == "" else value)


@pytest.mark.parametrize("second_pk", [40, 41])
def test_repeated_parameter_or_template_on_part(fixture_record, second_pk):
    raw = fixture_record("part_with_parameters")
    another = fixture_record("part_with_parameters")["parameters"][0]
    another["pk"] = second_pk
    raw["parameters"].append(another)
    with pytest.raises(adapters.AdapterError, match="Part pk=20.*duplicate"):
        adapters.part_with_parameters(raw)


def test_diagnostic_template_preserves_units(fixture_record):
    raw = fixture_record("template")
    raw["units"] = "Ω"
    assert adapters.parameter_template(raw).units == "Ω"

