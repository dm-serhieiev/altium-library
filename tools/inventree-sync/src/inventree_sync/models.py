"""Minimal immutable models, independent of transport field names."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Category:
    pk: int
    name: str
    parent_pk: int | None


@dataclass(frozen=True, slots=True)
class Part:
    pk: int
    ipn: str | None
    category_pk: int | None


@dataclass(frozen=True, slots=True)
class ParameterTemplate:
    pk: int
    name: str


@dataclass(frozen=True, slots=True)
class Parameter:
    pk: int
    part_pk: int
    template_pk: int
    data: str | None

