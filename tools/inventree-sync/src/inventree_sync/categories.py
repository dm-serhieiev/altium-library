"""Category topology and export-candidate validation, never parameter inheritance."""

from collections.abc import Iterable
from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Mapping

from .models import Category, Part

# Union of Microsoft Access and ACE reserved identifiers, reviewed 2026-10-02:
# https://support.microsoft.com/en-us/access/learn-about-access-reserved-words-and-symbols
# https://support.microsoft.com/en-us/access/sql-reserved-words
# This is a software validation contract, not a copy of InvenTree component data.
_RESERVED = frozenset("""
ABSOLUTE ACTION ADD ADMINDB ALL ALLOCATE ALPHANUMERIC ALTER AND ANY APPLICATION
ARE AS ASC ASSERTION ASSISTANT AT AUTHORIZATION AUTOINCREMENT AVG BAND BEGIN
BETWEEN BINARY BIT BIT_LENGTH BNOT BOOLEAN BOR BOTH BXOR BY BYTE CASCADE CASCADED
CASE CAST CATALOG CHAR CHARACTER CHAR_LENGTH CHARACTER_LENGTH CHECK CLOSE
CLUSTERED COALESCE COLLATE COLLATION COLUMN COMMIT COMP COMPACTDATABASE
COMPRESSION CONNECT CONNECTION CONSTRAINT CONSTRAINTS CONTAINER CONTAINS CONTINUE
CONVERT CORRESPONDING COUNT COUNTER CREATE CREATEDATABASE CREATEDB CREATEFIELD
CREATEGROUP CREATEINDEX CREATEOBJECT CREATEPROPERTY CREATERELATION CREATETABLEDEF
CREATEUSER CREATEWORKSPACE CROSS CURRENCY CURRENT CURRENT_DATE CURRENT_TIME
CURRENT_TIMESTAMP CURRENT_USER CURRENTUSER CURSOR DATABASE DATE DATETIME DAY
DEALLOCATE DEC DECIMAL DECLARE DEFAULT DEFERRABLE DEFERRED DELETE DESC DESCRIBE
DESCRIPTION DESCRIPTOR DIAGNOSTICS DISALLOW DISCONNECT DISTINCT DISTINCTROW
DOCUMENT DOMAIN DOUBLE DROP ECHO ELSE END END-EXEC EQV ERROR ESCAPE EXCEPT
EXCEPTION EXCLUSIVECONNECT EXEC EXECUTE EXISTS EXIT EXTERNAL EXTRACT FALSE FETCH
FIELD FIELDS FILLCACHE FIRST FLOAT FLOAT4 FLOAT8 FOR FOREIGN FORM FORMS FOUND FROM
FULL FUNCTION GENERAL GET GETOBJECT GETOPTION GLOBAL GO GOTO GOTOPAGE GRANT GROUP
GUID HAVING HOUR IDENTITY IDLE IEEEDOUBLE IEEESINGLE IF IGNORE IMAGE IMMEDIATE IMP
IN INDEX INDEXES INDICATOR INHERITABLE INITIALLY INNER INPUT INSENSITIVE INSERT
INSERTTEXT INT INTEGER INTEGER1 INTEGER2 INTEGER4 INTERSECT INTERVAL INTO IS
ISOLATION JOIN KEY LANGUAGE LAST LASTMODIFIED LEADING LEFT LEVEL LIKE LOCAL LOGICAL
LOGICAL1 LONG LONGBINARY LONGCHAR LONGTEXT LOWER MACRO MATCH MAX MEMO MIN MINUTE MOD
MODULE MONEY MONTH MOVE NAME NAMES NATIONAL NATURAL NCHAR NEWPASSWORD NEXT NO NOT
NOTE NULL NULLIF NUMBER NUMERIC OBJECT OCTET_LENGTH OF OFF OLEOBJECT ON ONLY OPEN
OPENRECORDSET OPTION OR ORDER ORIENTATION OUTER OUTPUT OVERLAPS OWNERACCESS PAD
PARAMETER PARAMETERS PARTIAL PASSWORD PERCENT PIVOT POSITION PRECISION PREPARE
PRESERVE PRIMARY PRIOR PRIVILEGES PROC PROCEDURE PROPERTY PUBLIC QUERIES QUERY
QUIT READ REAL RECALC RECORDSET REFERENCES REFRESH REFRESHLINK REGISTERDATABASE
RELATION RELATIVE REPAINT REPAIRDATABASE REPORT REPORTS REQUERY RESTRICT REVOKE
RIGHT ROLLBACK ROWS SCHEMA SCREEN SCROLL SECOND SECTION SELECT SELECTSCHEMA
SELECTSECURITY SESSION SESSION_USER SET SETFOCUS SETOPTION SHORT SINGLE SIZE
SMALLINT SOME SPACE SQL SQLCODE SQLERROR SQLSTATE STDEV STDEVP STRING SUBSTRING
SUM SYSTEM_USER TABLE TABLEDEF TABLEDEFS TABLEID TEMPORARY TEXT THEN TIME TIMESTAMP
TIMEZONE_HOUR TIMEZONE_MINUTE TO TOP TRAILING TRANSACTION TRANSFORM TRANSLATE
TRANSLATION TRIM TRUE TYPE UNION UNIQUE UNIQUEIDENTIFIER UNKNOWN UPDATE
UPDATEIDENTITY UPDATEOWNER UPDATESECURITY UPPER USAGE USER USING VALUE VALUES VAR
VARBINARY VARCHAR VARP VARYING VIEW WHEN WHENEVER WHERE WITH WORK WORKSPACE WRITE
XOR YEAR YES YESNO ZONE
""".casefold().split()) | frozenset({"group by", "alter table"})


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
        not 1 <= len(category_name) <= 64
        or re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(?: [A-Za-z0-9]+)*", category_name) is None
        or category_name.casefold().startswith(("msys", "usys"))
        or category_name.casefold() in _RESERVED
    ):
        raise CategoryError("Invalid or reserved Access table name")


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
