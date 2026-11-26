"""Every public helper in `api/crud.py` must have a caller under `src/`.

`run_list` (issue #859) was the counterexample: an unscoped generic runner whose count
chain stripped only `order_by(None)`, so a caller passing an already-paged statement got
the page size back as the total. It had zero callers, so no test caught it. This guard
fails at the definition instead.

A helper used only inside `crud.py` counts as uncalled: inline it or move it.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from src.api.crud import InvalidQuery, QuerySpec, apply_query
from src.models.workspace import Role

SRC = Path(__file__).resolve().parents[1] / "src"
CRUD = SRC / "api" / "crud.py"


@pytest.fixture(autouse=True)
async def _clean_db():
    """Override conftest's DB reset: this suite only reads source files."""
    yield


def _read(path):
    return path.read_text(encoding="utf-8")


def _referenced(tree):
    """Every name a module mentions as an attribute or an import target."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            for alias in node.names:
                found.add(alias.name.split(".")[-1])
                found.add(alias.asname or alias.name)
    return found


def uncalled(src, crud):
    """Public names `crud` defines that no other module under `src` reaches by import."""
    defined = {
        node.name
        for node in ast.parse(_read(crud)).body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and not node.name.startswith("_")
    }
    callers = set()
    for path in src.rglob("*.py"):
        if path != crud:
            callers |= _referenced(ast.parse(_read(path)))
    # ponytail: an import counts even when the module never calls it, because ruff's
    # F401 fails an import the module never uses, so a bare name that shadows a crud
    # helper (a local or a parameter) is not a caller. Ceiling: a name reached only
    # through a string, getattr, a star import (ruff's F403 fails those) or locals().
    # Upgrade path: resolve the imports and require an `ast.Call`.
    return {name for name in defined if name not in callers}


def _tree(tmp_path, crud_src, siblings=None):
    """A synthetic `src/` holding `api/crud.py` plus one sibling module per name."""
    src = tmp_path / "src"
    (src / "api").mkdir(parents=True)
    (src / "api" / "crud.py").write_text(crud_src, encoding="utf-8")
    for name, body in (siblings or {}).items():
        (src / f"{name}.py").write_text(body, encoding="utf-8")
    return src


@pytest.mark.parametrize("op", ["contains", "ncontains", "startswith", "endswith"])
def test_uuid_filters_reject_text_operators(op):
    with pytest.raises(InvalidQuery, match="does not support text operators"):
        apply_query(
            select(Role),
            Role,
            QuerySpec(filters=[("id", op, "00000000000000000000000000000001")]),
            sortable=set(),
            filterable={"id"},
        )


def test_uuid_filter_preserves_numeric_uuid_string():
    value = "00000000000000000000000000000001"
    stmt = apply_query(
        select(Role),
        Role,
        QuerySpec(filters=[("id", "eq", value)]),
        sortable=set(),
        filterable={"id"},
    )
    assert value in stmt.compile().params.values()


def test_no_uncalled_public_helpers_in_crud():
    dead = uncalled(SRC, CRUD)
    assert dead == set(), f"uncalled helpers in api/crud.py: {sorted(dead)}"


def test_comment_mentioning_a_helper_is_not_a_caller(tmp_path):
    """#946: the name has to reach a call, not a docstring, a comment or a string."""
    src = _tree(
        tmp_path,
        "def helper():\n    return 1\n",
        {"routes": '"""Call helper() when a list needs paging."""\n# helper()\nLIT = "helper()"\n'},
    )
    assert uncalled(src, src / "api" / "crud.py") == {"helper"}


def test_aliased_import_counts_as_a_caller(tmp_path):
    src = _tree(
        tmp_path,
        "def helper():\n    return 1\n",
        {"routes": "from api.crud import helper as h\n\nh()\n"},
    )
    assert uncalled(src, src / "api" / "crud.py") == set()


@pytest.mark.parametrize(
    "caller",
    [
        "import api.crud\n\napi.crud.helper()\n",
        "from api import crud\n\ncrud.helper()\n",
    ],
)
def test_module_attribute_call_counts_as_a_caller(tmp_path, caller):
    src = _tree(tmp_path, "def helper():\n    return 1\n", {"routes": caller})
    assert uncalled(src, src / "api" / "crud.py") == set()


def test_helper_called_only_inside_crud_is_reported(tmp_path):
    """The self-exclusion is a rule, not an oversight: an internal-only helper is dead."""
    crud = "def outer():\n    return inner()\n\n\ndef inner():\n    return 1\n"
    src = _tree(tmp_path, crud, {"routes": "from api.crud import outer\n\nouter()\n"})
    assert uncalled(src, src / "api" / "crud.py") == {"inner"}


def test_bare_name_without_an_import_is_not_a_caller(tmp_path):
    """A local named like a crud helper is not that helper: only imports and attributes count."""
    routes = "def helper():\n    return 1\n\n\ndef route(helper):\n    return helper()\n"
    src = _tree(tmp_path, "def helper():\n    return 1\n", {"routes": routes})
    assert uncalled(src, src / "api" / "crud.py") == {"helper"}


def test_reads_are_utf8_under_an_ascii_locale(tmp_path):
    """The guard must not fail on a non-ASCII source file before it reaches its verdict."""
    src = _tree(
        tmp_path,
        "def helper():\n    return 1\n",
        {"routes": '"""café — naïve."""\nfrom api.crud import helper\n\nhelper()\n'},
    )
    code = "import sys\nfrom pathlib import Path as P\nfrom tests.test_crud import uncalled\n"
    code += "print(sorted(uncalled(*map(P, sys.argv[1:]))))"
    done = subprocess.run(
        [sys.executable, "-c", code, str(src), str(src / "api" / "crud.py")],
        cwd=Path(__file__).resolve().parents[1],
        env={
            **os.environ,
            "LC_ALL": "C",
            "LANG": "C",
            "PYTHONUTF8": "0",
            "PYTHONCOERCECLOCALE": "0",
        },
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"


# --- parser: sort-dialect symmetry (#1057, #1013, #1134) -------------------


def _parse(query_string: str):
    """Run `parse_query` against a stub request; returns (spec, InvalidQuery|None)."""
    from starlette.requests import Request

    from src.api.crud import parse_query

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": query_string.encode(),
    }
    try:
        return parse_query(Request(scope)), None
    except InvalidQuery as exc:
        return None, str(exc)


def test_parse_rejects_order_only_in_both_dialects():
    """#1013 made `_order=desc` alone reject; #1134 makes it name the dialect.

    Symmetry: the same order-only query in the repeated dialect must reject
    with the same message shape, with the parameter names following the
    dialect the client actually used.
    """
    spec, err = _parse("_order=desc")
    assert spec is None
    assert err == "_sort and _order must have the same number of entries", err

    spec, err = _parse("order[]=desc")
    assert spec is None
    assert err == "sort[] and order[] must have the same number of entries", err


def test_parse_order_only_length_guard_beats_direction_check():
    """Which message an order-only query answers must not depend on the
    direction value: a bogus direction gets the same length guard (#1134)."""
    spec, err = _parse("_order=sideways")
    assert spec is None
    assert err == "_sort and _order must have the same number of entries", err

    spec, err = _parse("order[]=sideways")
    assert spec is None
    assert err == "sort[] and order[] must have the same number of entries", err


def test_parse_sort_dialect_symmetry_for_well_formed_queries():
    """Well-formed sort pairs parse identically in both dialects (#1013)."""
    comma, _ = _parse("_sort=name,created_at&_order=desc,asc")
    repeated, _ = _parse("sort[]=name&sort[]=created_at&order[]=desc&order[]=asc")
    assert comma.sort_by == repeated.sort_by == ["name", "created_at"]
    assert comma.sort_order == repeated.sort_order == ["desc", "asc"]
