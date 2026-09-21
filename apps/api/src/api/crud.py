"""Refine-compliant list/getMany query parsing for FastAPI + SQLAlchemy.

Implements the conventions of `@refinedev/simple-rest`:

    GET /{resource}?offset=0&limit=10&sort[]=created_at&order[]=desc
                    &acknowledged=false&created_at_like=foo
    GET /{resource}?ids[]=a&ids[]=b

Both the modern flat style (field=value, `field_ne=`, `field_gte=`,
`field_lte=`, `field_like=`) and the legacy `filter[field][op]=value` style
are accepted. Sort and filter fields are whitelisted per resource (never
trust client input for column names). Total count is returned via the
`X-Total-Count` header.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from sqlalchemy import Select, func, select
from sqlalchemy.sql import ColumnElement

_COMPARATORS = {
    "eq": lambda c, v: c == v,
    "ne": lambda c, v: c != v,
    "gt": lambda c, v: c > v,
    "gte": lambda c, v: c >= v,
    "lt": lambda c, v: c < v,
    "lte": lambda c, v: c <= v,
    "contains": lambda c, v: c.ilike(f"%{v}%"),
    "ncontains": lambda c, v: ~c.ilike(f"%{v}%"),
    "startswith": lambda c, v: c.ilike(f"{v}%"),
    "endswith": lambda c, v: c.ilike(f"%{v}"),
    "in": lambda c, v: c.in_([x for x in v.split(",") if x]),
    "nin": lambda c, v: ~c.in_([x for x in v.split(",") if x]),
    "isnull": lambda c, v: c.is_(None),
    "isnotnull": lambda c, v: c.is_not(None),
}

# simple-rest >= 6 serializes operators as a suffix on the bare field name
# (e.g. `field_ne=`, `field_like=`); older versions used `filter[field][op]=`.
_FIELD_SUFFIX_OPERATORS = {
    "_ne": "ne",
    "_gte": "gte",
    "_lte": "lte",
    "_like": "contains",
}


@dataclass
class QuerySpec:
    offset: int = 0
    limit: int = 10
    sort_by: list[str] = field(default_factory=list)
    sort_order: list[str] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)
    filters: list[tuple[str, str, str]] = field(default_factory=list)  # (field, op, value)


class InvalidQuery(Exception):
    pass


def parse_query(request: Request, *, max_limit: int = 100) -> QuerySpec:
    q = request.query_params
    spec = QuerySpec()
    try:
        # simple-rest server-side pagination (`_start`/`_end`) or the legacy
        # explicit `offset`/`limit`.
        if "_start" in q or "_end" in q:
            start = max(int(q.get("_start", "0")), 0)
            end = int(q.get("_end", str(start + 10)))
            if end <= start:
                raise InvalidQuery("_end must be greater than _start")
            spec.offset = start
            spec.limit = min(end - start, max_limit)
        else:
            spec.offset = max(int(q.get("offset", 0)), 0)
            spec.limit = min(max(int(q.get("limit", 10)), 1), max_limit)
    except ValueError:
        raise InvalidQuery("offset/limit must be integers") from None
    # simple-rest sorts with comma-joined `_sort`/`_order`; legacy uses
    # repeated `sort[]`/`order[]`.
    if "_sort" in q:
        spec.sort_by = [s for s in q.get("_sort", "").split(",") if s]
        orders = [s for s in q.get("_order", "").split(",") if s]
        spec.sort_order = orders + ["asc"] * (len(spec.sort_by) - len(orders))
    else:
        spec.sort_by = q.getlist("sort[]")
        spec.sort_order = q.getlist("order[]")
        if len(spec.sort_order) < len(spec.sort_by):
            spec.sort_order.extend(["asc"] * (len(spec.sort_by) - len(spec.sort_order)))
    spec.ids = q.getlist("ids[]")
    if not spec.ids and "id" in q:  # simple-rest getMany sends repeated `id=`
        spec.ids = q.getlist("id")
    for key, value in q.multi_items():
        if key == "q":
            continue  # cross-field search handled by the caller, not a column filter
        if key.startswith("filter[") and key.endswith("]"):
            field_name = key[len("filter[") : -1]
            if field_name.endswith("]"):
                op, _, inner = field_name.rpartition("[")
                spec.filters.append((inner, op, value))
            else:
                spec.filters.append((field_name, "eq", value))
        elif key in (
            "offset",
            "limit",
            "sort[]",
            "order[]",
            "ids[]",
            "_start",
            "_end",
            "_sort",
            "_order",
            "id",
        ):
            continue  # control params already parsed above
        else:
            for suffix, op in _FIELD_SUFFIX_OPERATORS.items():
                if key.endswith(suffix):
                    spec.filters.append((key[: -len(suffix)], op, value))
                    break
            else:
                spec.filters.append((key, "eq", value))
    return spec


def _coerce(column: ColumnElement, value: str) -> Any:
    """Best-effort type coercion so comparisons work on typed columns."""
    for candidate in (int, float):
        try:
            return candidate(value)
        except (ValueError, TypeError):
            continue
    return value


def apply_query(
    stmt: Select,
    model: type,
    spec: QuerySpec,
    *,
    sortable: set[str],
    filterable: set[str],
) -> Select:
    for fname, op, value in spec.filters:
        if fname not in filterable:
            raise InvalidQuery(f"filter on unknown field: {fname}")
        column = getattr(model, fname)
        if op not in _COMPARATORS:
            raise InvalidQuery(f"unsupported filter operator: {op}")
        stmt = stmt.where(_COMPARATORS[op](column, _coerce(column, value)))
    if spec.ids:
        stmt = stmt.where(model.id.in_(spec.ids))
    for fname, order in zip(spec.sort_by, spec.sort_order, strict=True):
        if fname not in sortable:
            raise InvalidQuery(f"sort on unknown field: {fname}")
        column = getattr(model, fname)
        stmt = stmt.order_by(column.desc() if order == "desc" else column.asc())
    return stmt


async def run_list(
    session,
    stmt: Select,
    model: type,
    request: Request,
    *,
    sortable: set[str],
    filterable: set[str],
) -> tuple[list[Any], int]:
    spec = parse_query(request)
    stmt = apply_query(stmt, model, spec, sortable=sortable, filterable=filterable)
    count = await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    total = count.scalar_one()
    stmt = stmt.offset(spec.offset).limit(spec.limit)
    result = await session.execute(stmt)
    return list(result.scalars().all()), total
