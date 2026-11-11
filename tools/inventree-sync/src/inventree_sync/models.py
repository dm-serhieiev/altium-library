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
    # None means metadata was not supplied by a diagnostic endpoint.
    # The primary nested adapter requires a textual units field (possibly "").
    units: str | None = None


@dataclass(frozen=True, slots=True)
class Parameter:
    pk: int
    part_pk: int
    template_pk: int
    data: str | None


@dataclass(frozen=True, slots=True)
class PartWithParameters:
    """One normalized response item; templates are shared when building a dataset."""

    part: Part
    parameters: tuple[Parameter, ...]
    templates: tuple[ParameterTemplate, ...]

    @property
    def pk(self) -> int:
        """Let the existing paginator detect repeated Part primary keys."""
        return self.part.pk

