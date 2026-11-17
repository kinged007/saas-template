"""The member-status policy tables must agree across the api/web split.

`WorkspaceService` decides suspend / reactivate / transfer per status from three
dicts in `apps/api/src/services/workspaces.py`; the web copy in
`apps/web/src/pages/member-actions.ts` decides the same three without a round
trip. The web tables are `Record<MemberStatus, boolean>`, so a status the domain
gains fails the web build until the table decides it — nothing catches the same
gap on the Python side, or a one-sided edit that flips one half of a pair. This
compares the two sources value for value.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
API_SRC = ROOT / "apps/api/src/services/workspaces.py"
WEB_SRC = ROOT / "apps/web/src/pages/member-actions.ts"

# api: `MemberStatus.ACTIVE.value: True` — web: `active: true`.
_API_ROW = re.compile(r"MemberStatus\.(\w+)\.value\s*:\s*(True|False)")
_WEB_ROW = re.compile(r"(\w+)\s*:\s*(true|false)")

TABLES = ["TRANSFER_ELIGIBLE", "SUSPEND_ALLOWED", "REACTIVATE_ALLOWED"]


@pytest.fixture(autouse=True)
async def _clean_db():
    """Override conftest's DB reset: this suite only reads the two sources."""
    yield


def _table(source: Path, name: str, row: re.Pattern) -> dict[str, bool]:
    """Extract one flat `{ status: bool }` literal by parsing it as text.

    The two sources have different syntax, so the dict literal is matched as
    text and the rows are read out of the captured body; the pairs are compared
    as data, not evaluated.
    """
    text = source.read_text(encoding="utf-8")
    declared = re.search(rf"\b_?{name}\b[^\n]*=\s*\{{", text)
    assert declared is not None, f"{name} table not found in {source}"
    body = text[declared.end() : text.index("}", declared.end())]
    return {status.lower(): value in {"True", "true"} for status, value in row.findall(body)}


@pytest.mark.parametrize("name", TABLES)
def test_web_table_matches_api(name: str):
    api = _table(API_SRC, name, _API_ROW)
    web = _table(WEB_SRC, name, _WEB_ROW)
    for status in sorted(set(api) | set(web)):
        assert status in api, f"{name}: web decides '{status}', the api table does not"
        assert status in web, f"{name}: api decides '{status}', the web table does not"
        assert api[status] == web[status], (
            f"{name} disagrees on '{status}': "
            f"api _{name} = {api[status]}, web {name} = {web[status]}"
        )
