"""Modern universal-parameter API adapter (no legacy field-name guessing).

Source contracts: InvenTree common/serializers.py ParameterSerializer and
InvenTree/serializers.py ContentTypeField (app_label.model_name), upstream master
reviewed 2026-10-02. Live-server/version compatibility remains unverified.
"""

from typing import Literal, overload

from .models import Category, Parameter, ParameterTemplate, Part

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
    return ParameterTemplate(_pk(obj, "pk", context), _text(obj, "name", context))


def parameter(raw: object) -> Parameter:
    obj, context = _record(raw, "Parameter")
    if _required(obj, "model_type", context) != PART_MODEL_TYPE:
        raise AdapterError(f"{context}: unsupported model_type; expected Part content type")
    part_pk = _pk(obj, "model_id", context)
    template_pk = _pk(obj, "template", context)
    context += f" Part pk={part_pk} template pk={template_pk}"
    data = _text(obj, "data", context, nullable=True)
    return Parameter(_pk(obj, "pk", context), part_pk, template_pk,
                     None if data == "" else data)

