"""Logical export validation; no SQL types, storage limits or database access."""

from typing import Mapping

from .models import ColumnDefinition, ModelKind, ModelRef, Parameter, ParameterTemplate, Part, TECHNICAL_COLUMNS


class ExportValidationError(ValueError):
    """The complete logical export cannot be prepared from the supplied data."""


class SchemaError(ExportValidationError):
    """An export column or an internal parameter reference is invalid."""


class ModelReferenceError(ExportValidationError):
    """An Altium model reference violates the library naming contract."""


def validate_column_name(name: str) -> None:
    """Keep the existing 64-character field-name contract, not table-name rules.

    Restrictions originate in the architecture's Access field-name convention:
    https://support.microsoft.com/en-us/access/guidelines-for-naming-fields-controls-and-objects
    Reserved SQL words (including Value and Description) are valid field names.
    """
    if (
        not isinstance(name, str) or not name or not name.strip()
        or len(name) > 64 or name[0].isspace()
        or any(c in ".!`[]" or ord(c) < 32 or ord(c) == 127 for c in name)
    ):
        raise SchemaError(f"Invalid output column name {name!r}; expected 1..64 characters without leading whitespace, controls or . ! ` [ ]")


def validate_columns(columns: tuple[ColumnDefinition, ...], context: str) -> None:
    seen: dict[str, ColumnDefinition] = {}
    for column in columns:
        source = f"template pk={column.template_pk}" if column.template_pk is not None else "technical column"
        try:
            validate_column_name(column.name)
        except SchemaError as exc:
            raise SchemaError(f"{context}, {source}: {exc}") from None
        key = column.name.casefold()
        if key in seen:
            previous = seen[key]
            origin = f"template pk={previous.template_pk}" if previous.template_pk is not None else "technical column"
            raise SchemaError(
                f"{context}: column {column.name!r} ({source}) conflicts with "
                f"{previous.name!r} ({origin})"
            )
        seen[key] = column


def validate_parameter_references(
    part: Part, parameters: Mapping[int, Parameter],
    templates: Mapping[int, ParameterTemplate], context: str,
) -> set[int]:
    """Check references while discovering the actual templates used by one Part."""
    referenced: set[int] = set()
    for template_pk, parameter in parameters.items():
        source = f"{context}, parameter pk={parameter.pk} template pk={parameter.template_pk}"
        if parameter.part_pk != part.pk:
            raise SchemaError(f"{source}: belongs to Part pk={parameter.part_pk}, expected Part pk={part.pk}")
        if template_pk != parameter.template_pk:
            raise SchemaError(f"{source}: parameter index key {template_pk} does not match template reference")
        template = templates.get(template_pk)
        if template is None:
            raise SchemaError(f"{source}: referenced ParameterTemplate is missing")
        if template.pk != template_pk:
            raise SchemaError(f"{source}: template index resolves to different pk={template.pk}")
        if parameter.data is not None and not isinstance(parameter.data, str):
            raise SchemaError(f"{source} name={template.name!r}: data must be str or None")
        referenced.add(template_pk)
    return referenced


def validate_model_uniqueness(
    ref: ModelRef, context: str,
    seen: dict[tuple[ModelKind, str], tuple[ModelRef, str]],
) -> None:
    """Register exported references, keeping symbol and footprint namespaces apart."""
    key = (ref.kind, ref.model_name.casefold())
    previous = seen.get(key)
    if previous is not None:
        other, other_context = previous
        if other.library_filename.casefold() != ref.library_filename.casefold():
            raise ExportValidationError(
                f"{context}: {ref.kind} model {ref.model_name!r} in {ref.library_filename!r} "
                f"conflicts with {other.library_filename!r} referenced by {other_context}"
            )
    else:
        seen[key] = (ref, context)


def validate_row(
    row: Mapping[str, str | None], columns: tuple[ColumnDefinition, ...], context: str,
) -> None:
    if tuple(row) != tuple(column.name for column in columns):
        raise ExportValidationError(f"{context}: row columns do not match the ordered table schema")
    for name, value in row.items():
        if value is not None and not isinstance(value, str):
            raise ExportValidationError(f"{context}: column {name!r} must contain str or None")
    for column in TECHNICAL_COLUMNS:
        value = row[column.name]
        if value is None or not value.strip():
            raise ExportValidationError(f"{context}: required technical column {column.name!r} is empty")
