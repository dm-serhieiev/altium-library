"""Prepare immutable Altium tables, with read-only library-file existence checks."""

from dataclasses import dataclass
import os
from pathlib import Path, PureWindowsPath
import re
from types import MappingProxyType
from typing import Mapping

from .models import ModelKind, ModelRef, Parameter, Part, PreparedTable, PreparedTables, TableSchema
from .retrieval import PreparedDataset
from .schema import build_table_schemas
from .validate import ExportValidationError, ModelReferenceError, validate_model_uniqueness, validate_row


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
    name: str, kind: ModelKind, columns_by_name: Mapping[str, int],
    parameters: Mapping[int, Parameter], context: str,
) -> ModelRef:
    template_pk = columns_by_name.get(name)
    if template_pk is None:
        raise ExportValidationError(f"{context}: missing required ParameterTemplate {name!r}")
    parameter = parameters.get(template_pk)
    source = f"{context}, template pk={template_pk} name={name!r}"
    if parameter is None:
        raise ExportValidationError(f"{source}: missing parameter assignment")
    if parameter.data is None or not parameter.data.strip():
        raise ExportValidationError(f"{source}, parameter pk={parameter.pk}: required model reference is empty")
    try:
        return parse_model_ref(parameter.data, kind)
    except ModelReferenceError as exc:
        raise ModelReferenceError(f"{source}, parameter pk={parameter.pk}: {exc}") from None


def _build_row(
    part: Part, parameters: Mapping[int, Parameter], schema: TableSchema,
    symbol: ModelRef, footprint: ModelRef, symbol_path: str, footprint_path: str,
) -> Mapping[str, str | None]:
    row: dict[str, str | None] = {
        "IPN": part.ipn,
        "Library Ref": symbol.model_name,
        "Library Path": symbol_path,
        "Footprint Ref": footprint.model_name,
        "Footprint Path": footprint_path,
    }
    for column in schema.columns:
        if column.template_pk is not None:
            parameter = parameters.get(column.template_pk)
            value = parameter.data if parameter is not None else None
            row[column.name] = None if value == "" else value
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
        columns_by_name = {c.name: c.template_pk for c in schema.columns if c.template_pk is not None}
        rows: list[Mapping[str, str | None]] = []
        for part in sorted(dataset.groups[schema.category_pk], key=lambda item: item.pk):
            context = f"Part pk={part.pk} IPN={part.ipn!r}, category pk={schema.category_pk} path={schema.category_path!r}"
            parameters = dataset.parameters[part.pk]
            symbol = _required_ref("Altium Symbol", "symbol", columns_by_name, parameters, context)
            footprint = _required_ref("Altium Footprint", "footprint", columns_by_name, parameters, context)
            for ref in (symbol, footprint):
                validate_model_uniqueness(ref, context, seen_models)
                key = (ref.kind, ref.library_filename)
                if key not in library_paths:
                    try:
                        library_paths[key] = resolve_model_path(ref, layout)
                    except ExportValidationError as exc:
                        raise ExportValidationError(f"{context}, {ref.kind} reference {ref!r}: {exc}") from None
            row = _build_row(part, parameters, schema, symbol, footprint,
                             library_paths[(symbol.kind, symbol.library_filename)],
                             library_paths[(footprint.kind, footprint.library_filename)])
            validate_row(row, schema.columns, context)
            rows.append(row)
        tables.append(PreparedTable(schema.category_pk, schema.name, schema.category_path, schema.columns, tuple(rows)))
    return PreparedTables(tuple(tables))
