from dataclasses import replace

import pytest

from inventree_sync.categories import build_category_tree
from inventree_sync.models import Category, Parameter, ParameterTemplate, TECHNICAL_COLUMNS
from inventree_sync.schema import build_table_schemas
from inventree_sync.validate import SchemaError


def test_union_includes_second_part_only_parameters(export_dataset):
    schemas = build_table_schemas(export_dataset)
    assert len(schemas) == 1
    schema = schemas[0]
    assert (schema.category_pk, schema.name, schema.category_path) == (2, "Resistors", "Components / Resistors")
    assert schema.columns[:5] == TECHNICAL_COLUMNS
    assert [(c.template_pk, c.name) for c in schema.columns[5:]] == [
        (10, "Altium Symbol"), (11, "Altium Footprint"), (30, "Value"),
        (31, "Package"), (35, "Power Rating"),
    ]


def test_order_does_not_depend_on_parts_or_mapping_order(export_dataset):
    shuffled = replace(
        export_dataset,
        groups={2: tuple(reversed(export_dataset.groups[2]))},
        parameters={pk: dict(reversed(tuple(values.items()))) for pk, values in export_dataset.parameters.items()},
        templates=dict(reversed(tuple(export_dataset.templates.items()))),
    )
    assert build_table_schemas(shuffled) == build_table_schemas(export_dataset)


def test_empty_categories_do_not_discover_schema_or_validate_names(export_dataset):
    tree = build_category_tree([
        Category(1, "Components", None), Category(2, "Resistors", 1),
        Category(3, "Invalid.Empty", 1), Category(4, "Connectors", 1),
    ])
    dataset = replace(export_dataset, tree=tree, groups={**export_dataset.groups, 3: ()})
    assert [s.name for s in build_table_schemas(dataset)] == ["Resistors"]


@pytest.mark.parametrize("name", ["Value", "Description", "Power Rating", "Mounting Type", "Tolerance (%)", "Опір", "A" * 64])
def test_exact_parameter_names_preserved(export_dataset, name):
    templates = {**export_dataset.templates, 30: ParameterTemplate(30, name), 35: ParameterTemplate(35, "Other Parameter")}
    schema = build_table_schemas(replace(export_dataset, templates=templates))[0]
    assert next(c for c in schema.columns if c.template_pk == 30).name == name


@pytest.mark.parametrize("name", [None, "", " ", " Leading", "A" * 65, "Bad.Name", "Bad!Name", "Bad`Name", "Bad[Name", "Bad]Name", "Bad\nName", "Bad\x00Name", "Bad\x7fName"])
def test_invalid_column_name_has_source_context(export_dataset, name):
    dataset = replace(export_dataset, templates={**export_dataset.templates, 30: ParameterTemplate(30, name)})
    with pytest.raises(SchemaError) as error:
        build_table_schemas(dataset)
    assert all(value in str(error.value) for value in ("Category pk=2", "Components / Resistors", "template pk=30", "column name"))


@pytest.mark.parametrize("name", ["IPN", "Library Ref", "library path", "Footprint Ref", "FOOTPRINT PATH"])
def test_technical_column_collision(export_dataset, name):
    dataset = replace(export_dataset, templates={**export_dataset.templates, 30: ParameterTemplate(30, name)})
    with pytest.raises(SchemaError, match="technical column"):
        build_table_schemas(dataset)


@pytest.mark.parametrize("name", ["Value", "vAlUe"])
def test_two_templates_cannot_resolve_to_same_column(export_dataset, name):
    dataset = replace(export_dataset, templates={**export_dataset.templates, 31: ParameterTemplate(31, name)})
    with pytest.raises(SchemaError) as error:
        build_table_schemas(dataset)
    assert all(value in str(error.value) for value in ("template pk=30", "template pk=31", "conflicts"))


@pytest.mark.parametrize("defect", ["missing", "wrong_pk", "wrong_part", "wrong_key", "nontext"])
def test_invalid_parameter_references(export_dataset, defect):
    templates = dict(export_dataset.templates)
    parameters = {pk: dict(values) for pk, values in export_dataset.parameters.items()}
    if defect == "missing":
        del templates[30]
    elif defect == "wrong_pk":
        templates[30] = ParameterTemplate(300, "Value")
    elif defect == "wrong_part":
        parameters[20][30] = replace(parameters[20][30], part_pk=21)
    elif defect == "wrong_key":
        parameters[20][30] = replace(parameters[20][30], template_pk=31)
    else:
        parameters[20][30] = replace(parameters[20][30], data=123)
    with pytest.raises(SchemaError) as error:
        build_table_schemas(replace(export_dataset, parameters=parameters, templates=templates))
    assert all(value in str(error.value) for value in ("Part pk=20", "IPN=", "parameter pk=102", "template pk="))


@pytest.mark.parametrize("defect", ["missing_parameters", "extra_parameters", "missing_group", "duplicate_part", "wrong_group", "empty"])
def test_inconsistent_dataset_cannot_drop_parts_or_parameters(export_dataset, defect):
    dataset = export_dataset
    if defect == "missing_parameters":
        dataset = replace(dataset, parameters={21: dataset.parameters[21]})
    elif defect == "extra_parameters":
        dataset = replace(dataset, parameters={**dataset.parameters, 999: {}})
    elif defect == "missing_group":
        dataset = replace(dataset, groups={2: dataset.groups[2][:1]})
    elif defect == "duplicate_part":
        dataset = replace(dataset, groups={2: (*dataset.groups[2], dataset.parts[20])})
    elif defect == "wrong_group":
        dataset = replace(dataset, groups={4: dataset.groups[2]})
    else:
        dataset = replace(dataset, groups={})
    with pytest.raises(SchemaError):
        build_table_schemas(dataset)


def test_parent_category_reuses_existing_validation(export_dataset):
    with pytest.raises(SchemaError, match="not a leaf"):
        build_table_schemas(replace(export_dataset, groups={1: export_dataset.groups[2]}))


def test_schema_does_not_apply_backend_field_count_limit(export_dataset):
    templates = dict(export_dataset.templates)
    parameters = dict(export_dataset.parameters[20])
    for pk in range(200, 460):
        templates[pk] = ParameterTemplate(pk, f"Parameter {pk}")
        parameters[pk] = Parameter(pk + 1000, 20, pk, "text")
    dataset = replace(export_dataset, templates=templates, parameters={**export_dataset.parameters, 20: parameters})
    assert len(build_table_schemas(dataset)[0].columns) > 255
