"""Read a category-scoped dataset; no schema generation or database writes."""

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from requests.auth import HTTPBasicAuth

from .api import InvenTreeClient
from .categories import CategoryTree, build_category_tree, group_parts, validate_part_placement
from .config import Config, load_config
from .models import Parameter, ParameterTemplate, Part


class DatasetError(ValueError):
    """Conflicting or repeated identities in an otherwise normalized response."""


@dataclass(frozen=True)
class PreparedDataset:
    tree: CategoryTree
    root_category_pk: int
    scope_category_pks: frozenset[int]
    parts: Mapping[int, Part]
    parameters: Mapping[int, Mapping[int, Parameter]]  # Part PK -> template PK
    templates: Mapping[int, ParameterTemplate]
    groups: Mapping[int, tuple[Part, ...]]  # Non-empty leaf category PK -> Parts


def retrieve_dataset(config_path: str | Path | Config, auth: HTTPBasicAuth | None = None) -> PreparedDataset:
    """Load config and fetch exactly categories plus scoped, nested Parts.

    Return only after all pages and local validations succeed. There is no
    automatic fallback to standalone parameter/template endpoints.
    """
    config = config_path if isinstance(config_path, Config) else load_config(config_path)
    with InvenTreeClient(config.inventree, auth=auth) as client:
        tree = build_category_tree(client.iter_categories())
        root_pk = tree.resolve_path(config.scope.root_category_path)
        scope = tree.subtree(root_pk)
        parts: dict[int, Part] = {}
        parameters: dict[int, Mapping[int, Parameter]] = {}
        templates: dict[int, ParameterTemplate] = {}
        template_sources: dict[int, int] = {}
        parameter_sources: dict[int, int] = {}
        for item in client.iter_parts_with_parameters(root_pk):
            part = item.part
            validate_part_placement(part, tree, scope)
            if part.pk in parts:
                raise DatasetError(f"Duplicate Part pk={part.pk} IPN={part.ipn!r}")
            parts[part.pk] = part
            for template in item.templates:
                if template.pk in templates and templates[template.pk] != template:
                    raise DatasetError(
                        f"Part pk={part.pk} IPN={part.ipn!r}: conflicting metadata for "
                        f"template pk={template.pk} with Part pk={template_sources[template.pk]}"
                    )
                if template.pk not in templates:
                    templates[template.pk] = template
                    template_sources[template.pk] = part.pk
            part_parameters: dict[int, Parameter] = {}
            for parameter in item.parameters:
                if parameter.pk in parameter_sources:
                    raise DatasetError(
                        f"Part pk={part.pk}: duplicate parameter pk={parameter.pk} "
                        f"with Part pk={parameter_sources[parameter.pk]}"
                    )
                parameter_sources[parameter.pk] = part.pk
                part_parameters[parameter.template_pk] = parameter
            parameters[part.pk] = MappingProxyType(part_parameters)
        groups = group_parts(parts.values(), tree, root_pk)
    return PreparedDataset(
        tree, root_pk, scope, MappingProxyType(parts), MappingProxyType(parameters),
        MappingProxyType(templates), MappingProxyType(groups),
    )
