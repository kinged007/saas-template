"""Contract of the deployment-admin gate.

The gate raised through a builder named `deployment_admin_denied`, which read
as a bool predicate but returned an always-truthy HTTPException. These tests
pin the replacement: a guard that raises, so no call site can test it as a
value, and one 403 per kind of denied caller.
"""

import pytest
from fastapi import HTTPException, status

from src.api import deps
from src.api.deps import AuthPrincipal
from src.models.api_key import ApiKey
from src.models.workspace import User


def _session_user(*, superuser: bool) -> AuthPrincipal:
    return AuthPrincipal(user=User(email="a@b.c", display_name="U", is_superuser=superuser))


def _key_user(*, superuser: bool) -> AuthPrincipal:
    # A key resolves to its creator's user, so the flag can be set on a key
    # principal too — it must still be denied.
    return AuthPrincipal(
        user=User(email="d@e.f", display_name="K", is_superuser=superuser),
        api_key=ApiKey(),
    )


def test_predicate_shaped_gate_is_gone():
    assert not hasattr(deps, "deployment_admin_denied")


@pytest.mark.parametrize(
    ("principal", "detail"),
    [
        (_key_user(superuser=False), "deployment administration is not available to API keys"),
        (_key_user(superuser=True), "deployment administration is not available to API keys"),
        (_session_user(superuser=False), "superuser access required"),
    ],
)
def test_gate_raises_one_403_per_kind_of_denied_caller(principal: AuthPrincipal, detail: str):
    with pytest.raises(HTTPException) as caught:
        deps.raise_deployment_admin_denied(principal)
    assert caught.value.status_code == status.HTTP_403_FORBIDDEN
    assert caught.value.detail == detail


def test_gate_is_silent_for_a_session_superuser():
    # The anti-trap property: an allowed caller gets None, never a truthy
    # exception object.
    assert deps.raise_deployment_admin_denied(_session_user(superuser=True)) is None
