"""InvenTree 1.5.6 / API schema 530 adapter (no legacy field-name guessing).

Source contracts: InvenTree common/serializers.py ParameterSerializer and
part/serializers.py PartSerializer and common/filters.py enable_parameters_filter,
upstream tag 1.5.6 reviewed 2026-11-11. Live-server compatibility remains unverified.
"""

from typing import Literal, overload

from .models import Category, Parameter, ParameterTemplate, Part, PartWithParameters

CATEGORIES_ENDPOINT = "part/category/"
PARTS_ENDPOINT = "part/"
TEMPLATES_ENDPOINT = "parameter/template/"
PARAMETERS_ENDPOINT = "parameter/"
PART_MODEL_TYPE = "part.part"


class AdapterError(ValueError):
    """An API record does not satisfy the supported wire contract."""


def _record(raw: object, kind: str) -> tuple[dict[str, object], str]:
    if not isinstance(raw, dict):
        raise AdapterError(f"{kind}: expected an API object")
    pk = raw.get("pk")
    context = f"{kind} pk={pk}" if type(pk) is int else kind
    return raw, context


def _required(raw: dict[str, object], field: str, context: str) -> object:
    if field not in raw:
        raise AdapterError(f"{context}: missing API field '{field}'")
    return raw[field]


@overload
def _pk(raw: dict[str, object], field: str, context: str, *, nullable: Literal[False] = False) -> int: ...


@overload
def _pk(raw: dict[str, object], field: str, context: str, *, nullable: Literal[True]) -> int | None: ...


def _pk(raw: dict[str, object], field: str, context: str, *, nullable: bool = False) -> int | None:
    value = _required(raw, field, context)
    if nullable and value is None:
        return None
    if type(value) is not int or value <= 0:
        raise AdapterError(f"{context}: '{field}' must be a positive integer PK")
    return value


@overload
def _text(raw: dict[str, object], field: str, context: str, *, nullable: Literal[False] = False) -> str: ...


@overload
def _text(raw: dict[str, object], field: str, context: str, *, nullable: Literal[True]) -> str | None: ...


def _text(raw: dict[str, object], field: str, context: str, *, nullable: bool = False) -> str | None:
    value = _required(raw, field, context)
    if nullable and value is None:
        return None
    if not isinstance(value, str):
        raise AdapterError(f"{context}: '{field}' must be textual")
    return value


def category(raw: object) -> Category:
    obj, context = _record(raw, "Category")
    return Category(_pk(obj, "pk", context), _text(obj, "name", context),
                    _pk(obj, "parent", context, nullable=True))


def part(raw: object) -> Part:
    obj, context = _record(raw, "Part")
    return Part(_pk(obj, "pk", context), _text(obj, "IPN", context, nullable=True),
                _pk(obj, "category", context, nullable=True))


def parameter_template(raw: object) -> ParameterTemplate:
    obj, context = _record(raw, "ParameterTemplate")
    units = _text(obj, "units", context) if "units" in obj else None
    return ParameterTemplate(_pk(obj, "pk", context), _text(obj, "name", context), units)


def parameter(raw: object, *, expected_part_pk: int | None = None) -> Parameter:
    obj, context = _record(raw, "Parameter")
    parameter_pk = _pk(obj, "pk", context)
    # A nested record has an explicit parent Part; validate model_type if supplied.
    # Standalone diagnostic records still require it to establish the target type.
    if (expected_part_pk is None or "model_type" in obj) and _required(obj, "model_type", context) != PART_MODEL_TYPE:
        raise AdapterError(f"{context}: unsupported model_type; expected Part content type")
    part_pk = _pk(obj, "model_id", context)
    template_pk = _pk(obj, "template", context)
    context += f" Part pk={part_pk} template pk={template_pk}"
    if expected_part_pk is not None and part_pk != expected_part_pk:
        raise AdapterError(f"{context}: parameter belongs to a different Part; expected Part pk={expected_part_pk}")
    data = _text(obj, "data", context, nullable=True)
    return Parameter(parameter_pk, part_pk, template_pk,
                     None if data == "" else data)


def part_with_parameters(raw: object) -> PartWithParameters:
    obj, context = _record(raw, "Part")
    component = part(obj)
    records = _required(obj, "parameters", context)
    if not isinstance(records, list):
        raise AdapterError(f"{context}: 'parameters' must be a list")
    parameters: list[Parameter] = []
    templates: dict[int, ParameterTemplate] = {}
    seen_pks: set[int] = set()
    for record in records:
        try:
            value = parameter(record, expected_part_pk=component.pk)
            parameter_context = f"Parameter pk={value.pk} template pk={value.template_pk}"
            nested, _ = _record(record, parameter_context)
            detail, detail_context = _record(
                _required(nested, "template_detail", parameter_context),
                f"{parameter_context} template_detail",
            )
            # Required in the primary 1.5.6 contract, even for unitless templates.
            _text(detail, "units", detail_context)
            template = parameter_template(detail)
            if template.pk != value.template_pk:
                raise AdapterError(f"{parameter_context}: template_detail.pk={template.pk} does not match template reference")
            if value.pk in seen_pks:
                raise AdapterError(f"{parameter_context}: duplicate parameter PK")
            if template.pk in templates:
                raise AdapterError(f"{parameter_context}: duplicate parameter template on Part")
            seen_pks.add(value.pk)
            templates[template.pk] = template
            parameters.append(value)
        except AdapterError as exc:
            raise AdapterError(f"{context}: {exc}") from None
    return PartWithParameters(component, tuple(parameters), tuple(templates.values()))

