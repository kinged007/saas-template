"""Nothing pinned INVITATIONS_ROUTE to the frontend route it names (#578).

``src.workflows.INVITATIONS_ROUTE`` is the URL the invitation notification's
"Open" button links to. Its value is a hand-maintained copy of the SPA route
``<Route path="invitations" .../>`` in ``apps/web/src/App.tsx``. The dev seed
and the workflow both import the constant, so those two backend sides cannot
drift from each other (``test_seed_notifications``), but nothing checked the
value against the frontend: rename the SPA route and the backend keeps
advertising a URL the frontend no longer serves — the #212 "Open"-button dead
end one hop further out. This reads the route table and fails when the constant
and the served route disagree.
"""

import re
from pathlib import Path

import pytest

from src.workflows import INVITATIONS_ROUTE

ROOT = Path(__file__).resolve().parents[3]
APP_TSX = ROOT / "apps/web/src/App.tsx"


@pytest.fixture(autouse=True)
async def _clean_db():
    """Override conftest's DB reset: this suite reads a source file, never the API."""
    yield


def _invitations_route_from_app_tsx(source: str) -> str:
    """Return the absolute path the App.tsx invitations route serves.

    Anchors on the ``ReceivedInvitationsPage`` element, so it reads that route's
    ``path`` and no other, then joins a relative (nested) declaration such as
    ``path="invitations"`` onto ``/``.
    """
    match = re.search(
        r'<Route\s+path="([^"]+)"\s+element=\{<ReceivedInvitationsPage\s*/>\}', source
    )
    assert match, (
        f"no invitations <Route> rendering ReceivedInvitationsPage in {APP_TSX}; "
        "update this guard if that route's element is rewritten"
    )
    path = match.group(1)
    return path if path.startswith("/") else f"/{path}"


def test_invitations_route_constant_matches_frontend_route():
    """INVITATIONS_ROUTE must equal the invitations route App.tsx serves (#578)."""
    frontend_route = _invitations_route_from_app_tsx(APP_TSX.read_text())
    assert frontend_route == INVITATIONS_ROUTE, (
        f"src.workflows.INVITATIONS_ROUTE is {INVITATIONS_ROUTE!r} but the frontend "
        f"serves the invitations screen at {frontend_route!r}; the notification Open "
        "button would be a dead end — update INVITATIONS_ROUTE to match the frontend route"
    )
