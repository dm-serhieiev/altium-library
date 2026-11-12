"""Discover logical columns from actual Part parameters, never category defaults."""

from .categories import CategoryError, validate_export_names
from .models import ColumnDefinition, TableSchema, TECHNICAL_COLUMNS
from .retrieval import PreparedDataset
from .validate import SchemaError, validate_columns, validate_parameter_references


EXCLUDED_EXPORT_PARAMETERS = frozenset({
    "KiCad Symbol", "KiCad Footprint", "Altium Symbol", "Altium Footprint",
})


def build_table_schemas(dataset: PreparedDataset) -> tuple[TableSchema, ...]:
    """Build schemas in category PK order using the already validated 1B groups.

    Validate index consistency at this public boundary so manually assembled
    datasets cannot silently lose Parts or parameter assignments.
    """
    category_pks = sorted(pk for pk, parts in dataset.groups.items() if parts)
    try:
        validate_export_names(dataset.tree, category_pks)
    except CategoryError as exc:
        raise SchemaError(str(exc)) from None
    if not category_pks:
        raise SchemaError("Selected scope contains no exported Parts in leaf categories")
    schemas: list[TableSchema] = []
    seen_parts: set[int] = set()
    for category_pk in category_pks:
        category = dataset.tree.categories[category_pk]
        context = dataset.tree.describe(category_pk)
        if category_pk not in dataset.scope_category_pks:
            raise SchemaError(f"{context}: outside selected scope")
        template_pks: set[int] = set()
        for part in dataset.groups[category_pk]:
            source = f"{context}, Part pk={part.pk} IPN={part.ipn!r}"
            if part.pk in seen_parts:
                raise SchemaError(f"{source}: duplicate Part in export groups")
            if part.category_pk != category_pk or dataset.parts.get(part.pk) != part:
                raise SchemaError(f"{source}: group does not match the Part index/category")
            if part.pk not in dataset.parameters:
                raise SchemaError(f"{source}: missing Part parameter index (use an empty mapping for no parameters)")
            seen_parts.add(part.pk)
            template_pks.update(validate_parameter_references(
                part, dataset.parameters[part.pk], dataset.templates, source,
            ))
        columns = TECHNICAL_COLUMNS + tuple(
            ColumnDefinition(dataset.templates[pk].name, pk) for pk in sorted(template_pks)
            if dataset.templates[pk].name not in EXCLUDED_EXPORT_PARAMETERS
        )
        validate_columns(columns, context)
        schemas.append(TableSchema(category_pk, category.name, dataset.tree.full_path(category_pk), columns))
    if seen_parts != set(dataset.parts):
        raise SchemaError(f"Parts absent from export groups: {sorted(set(dataset.parts) - seen_parts)}")
    if set(dataset.parameters) != seen_parts:
        raise SchemaError(f"Parameter indexes for unknown/unexported Parts: {sorted(set(dataset.parameters) - seen_parts)}")
    return tuple(schemas)
