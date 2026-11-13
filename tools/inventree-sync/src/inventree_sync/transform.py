"""Prepare immutable Altium tables, with read-only library-file existence checks."""

from dataclasses import dataclass
import os
from pathlib import Path, PureWindowsPath
import re
from types import MappingProxyType
from typing import Mapping

from .models import ModelKind, ModelRef, Parameter, ParameterTemplate, Part, PreparedTable, PreparedTables, TableSchema
from .retrieval import PreparedDataset
from .schema import build_table_schemas
from .validate import ExportValidationError, ModelReferenceError, validate_model_uniqueness, validate_row


# Suffix recognition only: these are not category schemas or conversion factors.
_SI_PREFIXES = frozenset("q r y z a f p n u µ μ m c d h k M G T P E Z Y R Q".split()) | {"da"}
_UNIT_BASES = {unit: unit for unit in ("V", "A", "F", "H", "W", "Hz", "s", "m", "g", "K", "°C", "%")}
_UNIT_BASES.update({"ohm": "ohm", "Ω": "ohm", "Ω": "ohm"})
_MAGNITUDE = re.compile(r"\s*[+-]?(?:[0-9]+(?:[.,][0-9]*)?|[.,][0-9]+)(?:[eE][+-]?[0-9]+)?")


def _unit_base(suffix: str) -> str | None:
    if suffix in _UNIT_BASES:
        return _UNIT_BASES[suffix]
    for prefix in _SI_PREFIXES:
        remainder = suffix[len(prefix):].lstrip()
        if suffix.startswith(prefix) and remainder in _UNIT_BASES:
            return _UNIT_BASES[remainder]
    return None


def format_parameter_value(data: str | None, units: str | None) -> str | None:
    """Append metadata units to scalar text without numeric conversion.

    Recognize signed decimal/scientific magnitudes, optional SI prefixes and
    a small set of case-sensitive unit suffixes (including ohm/Ω/Ω aliases).
    Exact custom units also work. Unknown suffixes and non-scalar expressions
    with units are ambiguous and fail; this is not a general unit parser.
    Whitespace-only optional values retain the existing verbatim policy.
    """
    if data is None or data == "":
        return None
    if not units or not data.strip():
        return data
    if not isinstance(units, str) or not units.strip() or units != units.strip():
        raise ExportValidationError("configured units must be nonempty text without surrounding whitespace")
    magnitude = _MAGNITUDE.match(data)
    if magnitude is None:
        raise ExportValidationError("ambiguous value: expected a scalar magnitude with an optional unit suffix")
    suffix = data[magnitude.end():].strip()
    expected = _unit_base(units)
    actual = _unit_base(suffix)
    if suffix == units or (expected is not None and actual == expected):
        return data
    if suffix == "m":
        raise ExportValidationError("ambiguous suffix 'm': milli prefix or metre unit")
    if not suffix or suffix in _SI_PREFIXES:
        return f"{data} {units}"
    # Permit an SI prefix before an exact custom metadata unit, e.g. krpm.
    if any(suffix.startswith(prefix) and suffix[len(prefix):].lstrip() == units for prefix in _SI_PREFIXES):
        return data
    if actual is not None:
        raise ExportValidationError(f"conflicting physical unit suffix {suffix!r}")
    raise ExportValidationError(f"ambiguous or unsupported unit suffix {suffix!r}")


@dataclass(frozen=True, slots=True)
class LibraryLayout:
    """Absolute native paths, anchored by the caller (e.g. to a config directory).

    The target DbLib need not exist. Library files must exist when preparing
    tables. No directories or files are created, opened for writing or parsed.
    """

    dblib_path: Path
    symbols_dir: Path
    footprints_dir: Path

    def __post_init__(self) -> None:
        for name in ("dblib_path", "symbols_dir", "footprints_dir"):
            value = getattr(self, name)
            if not isinstance(value, Path) or not value.is_absolute():
                raise ExportValidationError(f"LibraryLayout.{name}={value!r}: expected an absolute native Path; resolve it against an explicit base directory")


def parse_model_ref(value: str, kind: ModelKind) -> ModelRef:
    """Parse a library basename and model; never trim or repair source names."""
    if kind not in ("symbol", "footprint"):
        raise ModelReferenceError(f"Unsupported model kind {kind!r}; expected symbol or footprint")
    context = f"invalid {kind} reference {value!r}"
    if not isinstance(value, str) or value.count(":") != 1:
        raise ModelReferenceError(f"{context}: expected '<library>:<model>' with exactly one colon")
    library, model = value.split(":")
    extension = ".SchLib" if kind == "symbol" else ".PcbLib"
    if "." in library:
        if not library.endswith(extension):
            raise ModelReferenceError(f"{context}: expected library extension {extension}")
        library = library[:-len(extension)]
    if re.fullmatch(r"[A-Z][A-Za-z0-9]*(?:_[A-Z][A-Za-z0-9]*)*", library) is None:
        raise ModelReferenceError(f"{context}: expected a PascalCase library basename with optional underscore qualifiers, not a path")
    if kind == "symbol":
        valid = re.fullmatch(r"[A-Z][A-Za-z0-9]*(?:_[A-Z0-9][A-Za-z0-9]*)*", model)
        if not valid or model in {"R", "C", "L"}:
            raise ModelReferenceError(f"{context}: expected a descriptive symbol name with uppercase word initials and underscore separators")
    else:
        # Covers passive, IC, connector and manufacturer families; no family list.
        valid = re.fullmatch(r"[A-Z][A-Z0-9]*(?:[_.-][A-Z0-9]+)*", model)
        if not valid:
            raise ModelReferenceError(f"{context}: expected an uppercase structured footprint name with underscore fields and decimal periods")
    return ModelRef(kind, library + extension, model)


def resolve_model_path(ref: ModelRef, layout: LibraryLayout) -> str:
    """Check a referenced library file and emit a Windows path relative to DbLib.

    Only file existence is checked, not the presence of the model inside it.
    """
    directory = layout.symbols_dir if ref.kind == "symbol" else layout.footprints_dir
    library = directory / ref.library_filename
    try:
        exists = library.is_file()
    except OSError as exc:
        raise ExportValidationError(f"Cannot check library file {library}: {exc.strerror}") from None
    if not exists:
        raise ExportValidationError(f"Missing library file: {library}")
    try:
        relative = os.path.relpath(library, start=layout.dblib_path.parent)
    except ValueError:
        raise ExportValidationError(f"Library {library} cannot be expressed relative to DbLib {layout.dblib_path} (different drives/shares)") from None
    return str(PureWindowsPath(*Path(relative).parts))


def _required_ref(
    name: str, kind: ModelKind, templates: Mapping[int, ParameterTemplate],
    parameters: Mapping[int, Parameter], context: str,
) -> ModelRef:
    template_pks = [pk for pk in parameters if templates[pk].name == name]
    if not template_pks:
        available = sorted(pk for pk, template in templates.items() if template.name == name)
        if not available:
            raise ExportValidationError(f"{context}: missing required ParameterTemplate {name!r}")
        raise ExportValidationError(f"{context}, template pks={available} name={name!r}: missing parameter assignment")
    if len(template_pks) != 1:
        raise ExportValidationError(f"{context}: ambiguous required ParameterTemplate name={name!r}, template pks={sorted(template_pks)}")
    template_pk = template_pks[0]
    parameter = parameters[template_pk]
    source = f"{context}, template pk={template_pk} name={name!r}"
    source += f", value={parameter.data!r} units={templates[template_pk].units!r}"
    if parameter.data is None or not parameter.data.strip():
        raise ExportValidationError(f"{source}, parameter pk={parameter.pk}: required model reference is empty")
    try:
        return parse_model_ref(parameter.data, kind)
    except ModelReferenceError as exc:
        raise ModelReferenceError(f"{source}, parameter pk={parameter.pk}: {exc}") from None


def _build_row(
    part: Part, parameters: Mapping[int, Parameter], schema: TableSchema,
    templates: Mapping[int, ParameterTemplate], context: str,
    symbol: ModelRef, footprint: ModelRef, symbol_path: str, footprint_path: str,
) -> Mapping[str, str | None]:
    row: dict[str, str | None] = {
        "IPN": part.ipn,
        "Library Ref": symbol.model_name,
        "Library Path": symbol_path,
        "Footprint Ref": footprint.model_name,
        "Footprint Path": footprint_path,
        "InvenTree PK": str(part.pk),
    }
    for column in schema.columns:
        if column.template_pk is not None:
            parameter = parameters.get(column.template_pk)
            template = templates[column.template_pk]
            value = parameter.data if parameter is not None else None
            try:
                row[column.name] = format_parameter_value(value, template.units)
            except ExportValidationError as exc:
                raise ExportValidationError(
                    f"{context}, template pk={template.pk} name={template.name!r}, "
                    f"value={value!r} units={template.units!r}: {exc}"
                ) from None
    return MappingProxyType(row)


def prepare_tables(dataset: PreparedDataset, layout: LibraryLayout) -> PreparedTables:
    """Transform a 1B dataset without network access or output writes.

    Either return a complete immutable export or raise ExportValidationError.
    Category, column and row order are by category PK, template PK and Part PK.
    """
    schemas = build_table_schemas(dataset)
    tables: list[PreparedTable] = []
    seen_models: dict[tuple[ModelKind, str], tuple[ModelRef, str]] = {}
    library_paths: dict[tuple[ModelKind, str], str] = {}
    for schema in schemas:
        rows: list[Mapping[str, str | None]] = []
        for part in sorted(dataset.groups[schema.category_pk], key=lambda item: item.pk):
            context = f"Part pk={part.pk} IPN={part.ipn!r}, category pk={schema.category_pk} path={schema.category_path!r}"
            parameters = dataset.parameters[part.pk]
            symbol = _required_ref("Altium Symbol", "symbol", dataset.templates, parameters, context)
            footprint = _required_ref("Altium Footprint", "footprint", dataset.templates, parameters, context)
            for ref in (symbol, footprint):
                validate_model_uniqueness(ref, context, seen_models)
                key = (ref.kind, ref.library_filename)
                if key not in library_paths:
                    try:
                        library_paths[key] = resolve_model_path(ref, layout)
                    except ExportValidationError as exc:
                        raise ExportValidationError(f"{context}, {ref.kind} reference {ref!r}: {exc}") from None
            row = _build_row(part, parameters, schema, dataset.templates, context, symbol, footprint,
                             library_paths[(symbol.kind, symbol.library_filename)],
                             library_paths[(footprint.kind, footprint.library_filename)])
            validate_row(row, schema.columns, context)
            rows.append(row)
        tables.append(PreparedTable(schema.category_pk, schema.name, schema.category_path, schema.columns, tuple(rows)))
    return PreparedTables(tuple(tables))
