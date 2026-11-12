"""Category topology and export-candidate validation, never parameter inheritance."""

from collections.abc import Iterable
from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Mapping

from .models import Category, Part


class CategoryError(ValueError):
    """Invalid category topology, export name or Part placement."""


@dataclass(frozen=True)
class CategoryTree:
    categories: Mapping[int, Category]
    children: Mapping[int | None, tuple[int, ...]]
    paths: Mapping[int, tuple[str, ...]]

    def is_leaf(self, pk: int) -> bool:
        self._require(pk)
        return not self.children[pk]

    def _require(self, pk: int) -> None:
        if pk not in self.categories:
            raise CategoryError(f"Unknown category pk={pk}")

    def full_path(self, pk: int) -> str:
        self._require(pk)
        return " / ".join(self.paths[pk])

    def describe(self, pk: int) -> str:
        self._require(pk)
        return f"Category pk={pk} name={self.categories[pk].name!r} path={self.full_path(pk)!r}"

    def resolve_path(self, path: tuple[str, ...]) -> int:
        candidates = [pk for pk, full in self.paths.items() if full == tuple(path)]
        if len(candidates) != 1:
            raise CategoryError(f"Scope path {path!r} resolves to {len(candidates)} categories; expected exactly one")
        return candidates[0]

    def subtree(self, root_pk: int) -> frozenset[int]:
        self._require(root_pk)
        found: set[int] = set()
        pending = [root_pk]
        while pending:
            pk = pending.pop()
            found.add(pk)
            pending.extend(self.children[pk])
        return frozenset(found)


def build_category_tree(categories: Iterable[Category]) -> CategoryTree:
    index: dict[int, Category] = {}
    for category in categories:
        if category.pk in index:
            raise CategoryError(f"Duplicate category pk={category.pk} name={category.name!r}")
        index[category.pk] = category
    children: dict[int | None, list[int]] = {None: []}
    children.update({pk: [] for pk in index})
    for category in index.values():
        if category.parent_pk is not None and category.parent_pk not in index:
            raise CategoryError(f"Category pk={category.pk} name={category.name!r}: missing parent pk={category.parent_pk}; full path unavailable")
        children[category.parent_pk].append(category.pk)
    paths: dict[int, tuple[str, ...]] = {}
    # Iterative parent walk supports deep trees without Python recursion limits.
    for start in sorted(index):
        pending: list[int] = []
        visiting: set[int] = set()
        pk: int | None = start
        while pk is not None and pk not in paths:
            if pk in visiting:
                raise CategoryError(f"Category cycle at pk={pk} name={index[pk].name!r}; chain={pending}; full path unavailable")
            visiting.add(pk)
            pending.append(pk)
            pk = index[pk].parent_pk
        prefix = paths[pk] if pk is not None else ()
        for current in reversed(pending):
            prefix = (*prefix, index[current].name)
            paths[current] = prefix
    return CategoryTree(
        MappingProxyType(index),
        MappingProxyType({pk: tuple(sorted(ids)) for pk, ids in children.items()}),
        MappingProxyType(paths),
    )


def validate_table_name(category_name: str) -> None:
    if (
        not isinstance(category_name, str)
        or category_name.casefold().startswith("sqlite_")
        or re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(?: [A-Za-z0-9]+)*", category_name) is None
    ):
        raise CategoryError("Invalid table name: expected English letters/digits and single internal spaces, starting with a letter; sqlite_ names are reserved")


def validate_export_names(tree: CategoryTree, category_pks: Iterable[int]) -> None:
    """Validate only leaf categories with exported Parts, not empty leaves."""
    seen: dict[str, int] = {}
    for pk in sorted(set(category_pks)):
        if not tree.is_leaf(pk):
            raise CategoryError(f"{tree.describe(pk)}: export candidate is not a leaf")
        category = tree.categories[pk]
        try:
            validate_table_name(category.name)
        except CategoryError as exc:
            raise CategoryError(f"{tree.describe(pk)}: {exc}") from None
        key = category.name.casefold()
        if key in seen:
            raise CategoryError(f"{tree.describe(pk)}: duplicate table name with {tree.describe(seen[key])}")
        seen[key] = pk


def validate_part_placement(part: Part, tree: CategoryTree, scope: frozenset[int]) -> None:
    context = f"Part pk={part.pk} IPN={part.ipn!r} category pk={part.category_pk}"
    if part.category_pk is None or part.category_pk not in tree.categories:
        raise CategoryError(f"{context}: missing/unknown category; full path unavailable")
    context += f" path={tree.full_path(part.category_pk)!r}"
    if not part.ipn or not part.ipn.strip():
        raise CategoryError(f"{context}: IPN is required; Part.name is not a fallback")
    if part.category_pk not in scope:
        raise CategoryError(f"{context}: outside selected scope")
    if not tree.is_leaf(part.category_pk):
        raise CategoryError(f"{context}: Part is stored directly in a non-leaf category")


def group_parts(
    selected_parts: Iterable[Part], tree: CategoryTree, root_pk: int
) -> dict[int, tuple[Part, ...]]:
    """Validate already selected Parts; never silently discard out-of-scope input.

    The caller selects Parts using tree.subtree(root_pk). Uncategorized Parts
    cannot be attributed to a named subtree; if explicitly selected, they fail.
    """
    scope = tree.subtree(root_pk)
    groups: dict[int, list[Part]] = {}
    pks: set[int] = set()
    ipns: dict[str, int] = {}
    for part in selected_parts:
        validate_part_placement(part, tree, scope)
        assert part.ipn is not None and part.category_pk is not None
        if part.pk in pks:
            raise CategoryError(f"Duplicate Part pk={part.pk} IPN={part.ipn!r}")
        pks.add(part.pk)
        key = part.ipn.casefold()
        if key in ipns:
            raise CategoryError(f"Part pk={part.pk} IPN={part.ipn!r}: duplicate IPN with Part pk={ipns[key]}")
        ipns[key] = part.pk
        groups.setdefault(part.category_pk, []).append(part)
    if not groups:
        raise CategoryError("Selected scope contains no exported Parts in leaf categories")
    validate_export_names(tree, groups)
    return {pk: tuple(sorted(parts, key=lambda p: p.pk)) for pk, parts in sorted(groups.items())}
