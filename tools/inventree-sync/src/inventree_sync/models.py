"""Minimal immutable models, independent of transport field names."""

from dataclasses import dataclass
from typing import Literal, Mapping


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


ModelKind = Literal["symbol", "footprint"]


@dataclass(frozen=True, slots=True)
class ModelRef:
    kind: ModelKind
    library_filename: str
    model_name: str


@dataclass(frozen=True, slots=True)
class ColumnDefinition:
    name: str
    template_pk: int | None  # None identifies a generated technical column.


TECHNICAL_COLUMNS = tuple(ColumnDefinition(name, None) for name in (
    "IPN", "Library Ref", "Library Path", "Footprint Ref", "Footprint Path", "InvenTree PK",
))


@dataclass(frozen=True, slots=True)
class TableSchema:
    category_pk: int
    name: str
    category_path: str
    columns: tuple[ColumnDefinition, ...]


@dataclass(frozen=True, slots=True)
class PreparedTable:
    category_pk: int
    name: str
    category_path: str
    columns: tuple[ColumnDefinition, ...]
    rows: tuple[Mapping[str, str | None], ...]


@dataclass(frozen=True, slots=True)
class PreparedTables:
    tables: tuple[PreparedTable, ...]

