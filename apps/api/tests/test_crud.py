"""Every public helper in `api/crud.py` must have a caller under `src/`.

`run_list` (issue #859) was the counterexample: an unscoped generic runner whose count
chain stripped only `order_by(None)`, so a caller passing an already-paged statement got
the page size back as the total. It had zero callers, so no test caught it. This guard
fails at the definition instead.
"""

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
CRUD = SRC / "api" / "crud.py"


def test_no_uncalled_public_helpers_in_crud():
    tree = ast.parse(CRUD.read_text())
    defined = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and not node.name.startswith("_")
    }
    callers = "\n".join(
        path.read_text()
        for path in SRC.rglob("*.py")
        if path != CRUD and "alembic" not in path.parts
    )
    uncalled = {name for name in defined if not re.search(rf"\b{name}\b", callers)}
    assert uncalled == set(), f"uncalled helpers in api/crud.py: {sorted(uncalled)}"
