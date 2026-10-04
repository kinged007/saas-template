"""The frontend /invitations route, pinned in one place (#570).

Every other Python site reads the constant, so a typo inside it would reach
the frontend unnoticed. The value is duplicated in the frontend
(apps/web/src/App.tsx), which no Python test can cover.

The second test pins the one site that builds an absolute URL from the route:
the invitation email, whose token-less branch has no other assertion.
"""

from src.core.routes import INVITATIONS_ROUTE


def test_invitations_route_pins_the_frontend_route_value():
    assert INVITATIONS_ROUTE == "/invitations"


async def test_invitation_email_without_a_token_links_to_the_constant(monkeypatch):
    from src.container import Container
    from src.email import factory as email_factory
    from src.events.bus import EventMetadata
    from src.events.factory import WorkflowRegistry
    from src.events.subjects import Subjects
    from src.settings import settings
    from src.workflows import build_workflows

    sent: list[str] = []

    async def capture(message):
        sent.append(f"{message.text_body}\n{message.html_body or ''}")

    # The handler imports send_email inside its body, so patch the source module.
    monkeypatch.setattr(email_factory, "send_email", capture)

    container = Container()
    registry = WorkflowRegistry(container.bus)
    build_workflows(registry, container.bus, container.connection_manager)
    handler = registry._entries[Subjects.WORKSPACE_INVITATION_CREATED][0]

    # No invitation_id, so no token is re-read and the link is the bare route.
    await handler(
        {
            "is_registered": False,
            "email": "stranger@example.com",
            "workspace_name": "Acme",
            "invited_by_name": "Ada",
        },
        EventMetadata(subject=Subjects.WORKSPACE_INVITATION_CREATED),
    )

    assert len(sent) == 1, sent
    assert f"{settings.frontend_url.rstrip('/')}{INVITATIONS_ROUTE}" in sent[0]
