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

import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from sqlalchemy import Select
from sqlalchemy.sql import ColumnElement

from src.db.base import StringUUID
from src.services.profile_helpers import escape_like

_COMPARATORS = {
    "eq": lambda c, v: c == v,
    "ne": lambda c, v: c != v,
    "gt": lambda c, v: c > v,
    "gte": lambda c, v: c >= v,
    "lt": lambda c, v: c < v,
    "lte": lambda c, v: c <= v,
    "contains": lambda c, v: c.ilike(f"%{escape_like(str(v))}%", escape="\\"),
    "ncontains": lambda c, v: ~c.ilike(f"%{escape_like(str(v))}%", escape="\\"),
    "startswith": lambda c, v: c.ilike(f"{escape_like(str(v))}%", escape="\\"),
    "endswith": lambda c, v: c.ilike(f"%{escape_like(str(v))}", escape="\\"),
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
    # Which sort dialect the client used, recorded by `parse_query` when it
    # detects it. Error messages name the parameters the client actually
    # sent (#1134).
    repeated_sort: bool = False

    def _sort_param_names(self) -> tuple[str, str]:
        return ("sort[]", "order[]") if self.repeated_sort else ("_sort", "_order")

    def validate_sort(self) -> None:
        """Reject a direction list that does not line up with the sort list.

        Called by `parse_query`, `apply_query`, and by the routes that sort
        in their service layer, so a malformed sort query answers the same
        on every route whether the client wrote `sort[]`/`order[]` or
        `_sort`/`_order`.
        """
        if len(self.sort_by) != len(self.sort_order):
            by, order = self._sort_param_names()
            raise InvalidQuery(f"{by} and {order} must have the same number of entries")


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
    # repeated `sort[]`/`order[]`. The dialect is read from either of its
    # parameters, so `_order` on its own is parsed (and rejected by the
    # length guard) rather than falling through to the repeated style and
    # being dropped.
    #
    # Dialect contract (#1059): the primary list path — refine's simple-rest
    # data provider (apps/web) — sends the comma dialect (`_sort`/`_order`,
    # e.g. `?_end=20&_order=desc&_sort=last_message_at&_start=0`). Only the
    # admin provider (apps/web/src/providers/dataProvider.ts) appends
    # repeated `sort[]`/`order[]`. The two spellings must be matched per
    # request; the guards below name the dialect the client actually used.
    repeated = "sort[]" in q or "order[]" in q
    spec.repeated_sort = repeated
    if repeated and ("_sort" in q or "_order" in q):
        # Name the mix here. Falling through reads it as an order with no
        # sort (or the reverse) and reports the length guard, whose message
        # names `sort[]`/`order[]` even when the client sent `_sort`/`_order`.
        raise InvalidQuery("mixing sort[]/order[] with _sort/_order is not supported")
    if repeated:
        sort_by, orders = q.getlist("sort[]"), q.getlist("order[]")
    else:
        sort_by = q.get("_sort", "").split(",")
        orders = q.get("_order", "").split(",")
    # An empty entry names no column, so it drops in both dialects: `_sort=,`
    # and `?sort[]=` both mean no sort.
    spec.sort_by = [s for s in sort_by if s]
    spec.sort_order = [o for o in orders if o]
    spec.sort_order.extend(["asc"] * (len(spec.sort_by) - len(spec.sort_order)))
    # `apply_query` compares the direction against the literals "desc"/"asc",
    # so normalize the client's value once here rather than at both call sites
    # (the leading term and the `id` tiebreaker). `DESC` is the SQL convention a
    # client may well send; unnormalized it took the `else` branch and sorted
    # ascending, silently.
    spec.sort_order = [o.strip().lower() for o in spec.sort_order]
    # The length guard runs before the direction check so an order-only
    # malformed query answers the length guard in both dialects regardless
    # of the direction value (#1134). Service-layer routes re-run it after
    # mutating the spec.
    spec.validate_sort()
    # `apply_query` reads anything but "desc" as ascending, so a misspelled
    # direction would come back 200 and oldest-first with nothing to notice.
    for o in spec.sort_order:
        if o not in ("asc", "desc"):
            raise InvalidQuery(f"sort order must be 'asc' or 'desc': {o}")
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
    if isinstance(column.type, StringUUID):
        return value
    for candidate in (int, float):
        try:
            return candidate(value)
        except (ValueError, TypeError):
            continue
    return value


def _validate_uuid_bind(column: ColumnElement, field_name: str, values: list[str]) -> None:
    """Reject values that cannot bind to a StringUUID column.

    StringUUID.process_bind_param calls uuid.UUID() on every str bind, so a
    malformed filter/ids value reaching the query raises StatementError -> 500;
    a query id is a client error (422), not a crash.
    """
    if not isinstance(column.type, StringUUID):
        return
    for value in values:
        try:
            uuid.UUID(value)
        except (TypeError, ValueError):
            raise InvalidQuery(f"{field_name} requires UUID values") from None


# Ops whose value is bound as-is; isnull/isnotnull never bind their value.
_VALUE_OPS = set(_COMPARATORS) - {"isnull", "isnotnull"}


# The common "newest first" list order, for routes that want one.
CREATED_DESC = (("created_at", "desc"),)


def apply_query(
    stmt: Select,
    model: type,
    spec: QuerySpec,
    *,
    sortable: set[str],
    filterable: set[str],
    default_sort: tuple[tuple[str, str], ...] = (),
) -> Select:
    """Apply filters, ids and ordering to `stmt`.

    `default_sort` is the order used when the caller sent no `sort[]`/`_sort`;
    a caller's terms win over it.
    """
    for fname, op, value in spec.filters:
        if fname not in filterable:
            raise InvalidQuery(f"filter on unknown field: {fname}")
        column = getattr(model, fname)
        if op not in _COMPARATORS:
            raise InvalidQuery(f"unsupported filter operator: {op}")
        if isinstance(column.type, StringUUID) and op in (
            "contains",
            "ncontains",
            "startswith",
            "endswith",
        ):
            raise InvalidQuery(f"{fname} does not support text operators")
        if op in _VALUE_OPS:
            # The in/nin comparator splits on comma and drops empty terms, so
            # validate exactly the terms it would bind.
            bound = [x for x in value.split(",") if x] if op in ("in", "nin") else [value]
            _validate_uuid_bind(column, fname, bound)
        stmt = stmt.where(_COMPARATORS[op](column, _coerce(column, value)))
    if spec.ids:
        _validate_uuid_bind(model.id, "id", spec.ids)
        stmt = stmt.where(model.id.in_(spec.ids))
    # A caller that sent no sort gets the route default whole: a stray
    # `order[]` with no `sort[]` cannot desynchronise the `zip(strict=True)`
    # below, so the length guard only runs on an explicit sort.
    if spec.sort_by:
        spec.validate_sort()
    # Resolved together: `zip(..., strict=True)` below consumes the two lists as
    # a pair, so independent fallbacks can desynchronise and 500.
    if spec.sort_by:
        sort_by, sort_order = list(spec.sort_by), list(spec.sort_order)
    else:
        sort_by, sort_order = [f for f, _ in default_sort], [o for _, o in default_sort]
    for fname, order in zip(sort_by, sort_order, strict=True):
        if fname not in sortable:
            raise InvalidQuery(f"sort on unknown field: {fname}")
        column = getattr(model, fname)
        stmt = stmt.order_by(column.desc() if order == "desc" else column.asc())
    # A unique column last makes the order total, so offset/limit paging can
    # neither repeat nor skip a row when the leading terms tie. Only where an
    # order already exists: making one up is not this helper's call.
    if sort_by and "id" not in sort_by:
        last = sort_order[-1] if sort_order else "asc"
        stmt = stmt.order_by(model.id.desc() if last == "desc" else model.id.asc())
    return stmt
