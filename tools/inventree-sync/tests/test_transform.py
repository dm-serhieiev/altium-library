from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from inventree_sync.models import ModelRef, Part
from inventree_sync.transform import LibraryLayout, parse_model_ref, prepare_tables, resolve_model_path
from inventree_sync.validate import ExportValidationError, ModelReferenceError


@pytest.mark.parametrize("value,kind,filename,model", [
    ("Passives:Resistor", "symbol", "Passives.SchLib", "Resistor"),
    ("Passives.SchLib:Resistor", "symbol", "Passives.SchLib", "Resistor"),
    ("Resistors:RES_0603_H0.55", "footprint", "Resistors.PcbLib", "RES_0603_H0.55"),
    ("Resistors.PcbLib:RES_0603_H0.55", "footprint", "Resistors.PcbLib", "RES_0603_H0.55"),
    ("Analog:OpAmp_Dual", "symbol", "Analog.SchLib", "OpAmp_Dual"),
    ("Connectors:Connector_USB_C", "symbol", "Connectors.SchLib", "Connector_USB_C"),
    ("Transistors:Transistor_NMOS", "symbol", "Transistors.SchLib", "Transistor_NMOS"),
    ("Diodes:LED", "symbol", "Diodes.SchLib", "LED"),
    ("MCU:STM32H723VGT6", "symbol", "MCU.SchLib", "STM32H723VGT6"),
    ("QFN:QFN_32_5X5_P0.5_EP3.4", "footprint", "QFN.PcbLib", "QFN_32_5X5_P0.5_EP3.4"),
    ("SOIC:SOIC_8_3.9X4.9_P1.27", "footprint", "SOIC.PcbLib", "SOIC_8_3.9X4.9_P1.27"),
    ("Resistors:RES_AXIAL_DIN0207_P10.16", "footprint", "Resistors.PcbLib", "RES_AXIAL_DIN0207_P10.16"),
    ("Connectors_Molex:MOLEX_43045_0812", "footprint", "Connectors_Molex.PcbLib", "MOLEX_43045_0812"),
    ("Connectors_JST:JST_B4B_PH_K", "footprint", "Connectors_JST.PcbLib", "JST_B4B_PH_K"),
])
def test_model_references(value, kind, filename, model):
    assert parse_model_ref(value, kind) == ModelRef(kind, filename, model)


@pytest.mark.parametrize("value,kind", [
    ("Resistor", "symbol"), (":Resistor", "symbol"), ("Passives:", "symbol"),
    ("Passives:Resistor:Extra", "symbol"), (r"C:\Libraries\Passives.SchLib:Resistor", "symbol"),
    ("../Passives:Resistor", "symbol"), (r"..\Passives:Resistor", "symbol"),
    ("/Passives:Resistor", "symbol"), ("Dir/Passives:Resistor", "symbol"),
    ("Passives.PcbLib:Resistor", "symbol"), ("Resistors.SchLib:RES_0603_H0.55", "footprint"),
    ("Passives.schlib:Resistor", "symbol"), ("Passives.Other.SchLib:Resistor", "symbol"),
    (" Passives:Resistor", "symbol"), ("Passives :Resistor", "symbol"),
    ("Passives: Resistor", "symbol"), ("Passives:Resistor ", "symbol"),
    ("Passives:Resistor\n", "symbol"), ("Passives:Resistor\x00", "symbol"),
    ("passives:Resistor", "symbol"), ("Passive-Parts:Resistor", "symbol"),
    ("Passive Parts:Resistor", "symbol"), ("Passives:resistor", "symbol"),
    ("Passives:Resistor_array", "symbol"), ("Passives:Resistor__Array", "symbol"),
    ("Passives:R", "symbol"), ("Passives:C", "symbol"), ("Passives:L", "symbol"),
    ("Passives:Резистор", "symbol"), ("Resistors:res_0603", "footprint"),
    ("QFN:QFN_32_5x5_P0.5", "footprint"), ("Resistors:RES__0603", "footprint"),
    ("Resistors:RES_0603_", "footprint"), ("Resistors:RES_0603_H0..55", "footprint"),
    ("Resistors:RES/0603", "footprint"), ("Resistors:../RES_0603", "footprint"),
    (None, "symbol"), ("", "footprint"), (" ", "symbol"), ("Passives:Resistor", "other"),
])
def test_invalid_model_references_are_not_repaired(value, kind):
    with pytest.raises(ModelReferenceError):
        parse_model_ref(value, kind)


def test_complete_rows_and_source_values(export_dataset, library_layout):
    result = prepare_tables(export_dataset, library_layout)
    assert len(result.tables) == 1
    table = result.tables[0]
    assert (table.category_pk, table.name, table.category_path) == (2, "Resistors", "Components / Resistors")
    first, second = table.rows
    assert dict(first) == {
        "IPN": "RES-10K-1%-0603",
        "Library Ref": "Resistor", "Library Path": r"..\symbols\Passives.SchLib",
        "Footprint Ref": "RES_0603_H0.55", "Footprint Path": r"..\footprints\Resistors.PcbLib",
        "Altium Symbol": "Passives:Resistor", "Altium Footprint": "Resistors:RES_0603_H0.55",
        "Value": "10 kΩ", "Package": "0603", "Power Rating": None,
    }
    assert second["Package"] is None and second["Power Rating"] == "0.125"
    assert second["Altium Symbol"] == "Passives.SchLib:Resistor"
    assert second["Altium Footprint"] == "Resistors.PcbLib:RES_0603_H0.55"
    assert tuple(first) == tuple(c.name for c in table.columns)


@pytest.mark.parametrize("value", ["0603", "1%", "1E3", "10 kΩ", "0.125", "=example", "  meaningful  ", " ", "1,25", "O'Brien", "x" * 10000, "", None])
def test_source_text_preserved(export_dataset, library_layout, value):
    parameters = {**export_dataset.parameters[20], 30: replace(export_dataset.parameters[20][30], data=value)}
    dataset = replace(export_dataset, parameters={**export_dataset.parameters, 20: parameters})
    assert prepare_tables(dataset, library_layout).tables[0].rows[0]["Value"] == (None if value == "" else value)


@pytest.mark.parametrize("template_pk", [10, 11])
@pytest.mark.parametrize("defect", ["no_template", "no_assignment", None, "", " \t ", "malformed"])
def test_required_parameters(export_dataset, library_layout, template_pk, defect):
    parameters = {pk: dict(values) for pk, values in export_dataset.parameters.items()}
    templates = dict(export_dataset.templates)
    if defect == "no_template":
        del templates[template_pk]
        for values in parameters.values():
            del values[template_pk]
    elif defect == "no_assignment":
        del parameters[20][template_pk]
    else:
        parameters[20][template_pk] = replace(parameters[20][template_pk], data=defect)
    with pytest.raises(ExportValidationError) as error:
        prepare_tables(replace(export_dataset, parameters=parameters, templates=templates), library_layout)
    message = str(error.value)
    assert "Part pk=20" in message and "IPN=" in message
    assert ("Altium Symbol" if template_pk == 10 else "Altium Footprint") in message


def test_mandatory_template_name_is_exact(export_dataset, library_layout):
    templates = {**export_dataset.templates, 10: replace(export_dataset.templates[10], name="altium symbol")}
    with pytest.raises(ExportValidationError, match="missing required ParameterTemplate 'Altium Symbol'"):
        prepare_tables(replace(export_dataset, templates=templates), library_layout)


@pytest.mark.parametrize("template_pk,filename", [(10, "Legacy.SchLib"), (11, "Legacy.PcbLib")])
def test_model_conflicts_across_parts_and_libraries(export_dataset, library_layout, template_pk, filename):
    directory = library_layout.symbols_dir if template_pk == 10 else library_layout.footprints_dir
    (directory / filename).write_bytes(b"dummy")
    original = export_dataset.parameters[21][template_pk]
    parameters = {**export_dataset.parameters[21], template_pk: replace(original, data="Legacy:" + original.data.split(":")[1])}
    with pytest.raises(ExportValidationError) as error:
        prepare_tables(replace(export_dataset, parameters={**export_dataset.parameters, 21: parameters}), library_layout)
    assert all(text in str(error.value) for text in ("conflicts", "Legacy", "Part pk=20", "Part pk=21"))


def test_deterministic_order_across_categories(export_dataset, library_layout):
    third = Part(15, "CON-EXAMPLE", 4)
    parts = {15: third, **dict(reversed(tuple(export_dataset.parts.items())))}
    parameters = {**export_dataset.parameters, 15: {pk: replace(p, pk=p.pk + 1000, part_pk=15) for pk, p in export_dataset.parameters[20].items()}}
    dataset = replace(export_dataset, parts=parts, parameters=parameters, groups={4: (third,), 2: tuple(reversed(export_dataset.groups[2]))})
    result = prepare_tables(dataset, library_layout)
    assert [t.category_pk for t in result.tables] == [2, 4]
    assert [r["IPN"] for r in result.tables[0].rows] == [export_dataset.parts[20].ipn, export_dataset.parts[21].ipn]
    assert result == prepare_tables(dataset, library_layout)


def test_input_unchanged_and_output_read_only(export_dataset, library_layout):
    before = repr(export_dataset)
    root = library_layout.symbols_dir.parent
    files_before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = prepare_tables(export_dataset, library_layout)
    assert repr(export_dataset) == before
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == files_before
    assert not library_layout.dblib_path.exists()
    with pytest.raises(FrozenInstanceError):
        result.tables = ()
    with pytest.raises(FrozenInstanceError):
        result.tables[0].name = "Other"
    with pytest.raises(FrozenInstanceError):
        result.tables[0].columns[0].name = "Other"
    with pytest.raises(TypeError):
        result.tables[0].rows[0]["IPN"] = "Other"


def test_later_failure_returns_no_partial_result_or_files(export_dataset, library_layout):
    original = export_dataset.parameters[21][11]
    bad = {**export_dataset.parameters[21], 11: replace(original, data="Missing:RES_0805_H0.60")}
    dataset = replace(export_dataset, parameters={**export_dataset.parameters, 21: bad})
    root = library_layout.symbols_dir.parent
    before_files = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = None
    with pytest.raises(ExportValidationError, match="Part pk=21.*Missing library file"):
        result = prepare_tables(dataset, library_layout)
    assert result is None
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before_files
    assert not library_layout.dblib_path.exists()


def test_path_is_relative_to_arbitrary_dblib_not_cwd(export_dataset, library_layout, tmp_path, monkeypatch):
    unrelated = tmp_path / "working"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    layout = replace(library_layout, dblib_path=tmp_path / "output" / "nested" / "Other.DbLib")
    row = prepare_tables(export_dataset, layout).tables[0].rows[0]
    assert row["Library Path"] == r"..\..\symbols\Passives.SchLib"
    assert row["Footprint Path"] == r"..\..\footprints\Resistors.PcbLib"


def test_library_next_to_dblib(library_layout):
    layout = replace(library_layout, dblib_path=library_layout.symbols_dir / "Other.DbLib")
    assert resolve_model_path(parse_model_ref("Passives:Resistor", "symbol"), layout) == "Passives.SchLib"


@pytest.mark.parametrize("field", ["dblib_path", "symbols_dir", "footprints_dir"])
def test_relative_layout_is_rejected(library_layout, field):
    with pytest.raises(ExportValidationError, match="absolute native Path"):
        replace(library_layout, **{field: Path("relative")})


@pytest.mark.parametrize("kind,name", [("symbol", "Passives.SchLib"), ("footprint", "Resistors.PcbLib")])
@pytest.mark.parametrize("is_directory", [False, True])
def test_missing_library_file(export_dataset, library_layout, kind, name, is_directory):
    directory = library_layout.symbols_dir if kind == "symbol" else library_layout.footprints_dir
    path = directory / name
    path.unlink()
    if is_directory:
        path.mkdir()  # A directory with the right suffix is not a library file.
    with pytest.raises(ExportValidationError) as error:
        prepare_tables(export_dataset, library_layout)
    assert str(path) in str(error.value) and "Part pk=20" in str(error.value)


def test_file_check_failure_is_a_contextual_error(export_dataset, library_layout, monkeypatch):
    def denied(path):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(Path, "is_file", denied)
    with pytest.raises(ExportValidationError, match="Part pk=20.*Cannot check library file"):
        prepare_tables(export_dataset, library_layout)


def test_unrepresentable_relative_path_is_not_replaced_with_absolute(library_layout, monkeypatch):
    def different_drives(*args, **kwargs):
        raise ValueError("different drives")
    monkeypatch.setattr("inventree_sync.transform.os.path.relpath", different_drives)
    with pytest.raises(ExportValidationError, match="different drives/shares"):
        resolve_model_path(parse_model_ref("Passives:Resistor", "symbol"), library_layout)
