"""Contract of the deployment-admin guard `require_deployment_admin` (deps.py).

The gate used to be an exception *builder* named `deployment_admin_denied`,
which read as a bool predicate but returned an always-truthy HTTPException. It
is now a guard that raises: `require_deployment_admin` returns None for an
allowed deployment admin and raises for everyone else, so no call site can read
it as a value. `require_superuser` delegates to it, and jobs.py's global
branches call it directly — the branch that used to be gated twice on
`is_deployment_admin` now is one line. The shared "superuser access required"
403 detail also binds `ProfileService.delete_account_superuser`. These tests
pin that contract.
"""

import pytest
from fastapi import HTTPException, status

from src.api import deps
from src.api.deps import AuthPrincipal
from src.core.permissions import SUPERUSER_ACCESS_REQUIRED
from src.models.api_key import ApiKey
from src.models.workspace import User
from src.services import profiles as profiles_service


def _session_user(*, superuser: bool) -> AuthPrincipal:
    return AuthPrincipal(user=User(email="a@b.c", display_name="U", is_superuser=superuser))


def _key_user(*, superuser: bool) -> AuthPrincipal:
    # A key resolves to its creator's user, so the flag can be set on a key
    # principal too — it must still be denied. `is_deployment_admin` is False
    # for any principal carrying an api_key.
    return AuthPrincipal(
        user=User(email="d@e.f", display_name="K", is_superuser=superuser),
        api_key=ApiKey(),
    )


def test_predicate_shaped_gate_is_gone():
    assert not hasattr(deps, "deployment_admin_denied")
    assert hasattr(deps, "require_deployment_admin")


def test_gate_returns_none_for_a_session_superuser():
    # The anti-trap property: an allowed caller gets None, never a truthy
    # exception object.
    assert deps.require_deployment_admin(_session_user(superuser=True)) is None


async def test_require_superuser_returns_user_for_a_session_superuser():
    # #1086: require_superuser delegates to the guard and yields the user on the
    # admin path instead of re-checking the condition itself.
    principal = _session_user(superuser=True)
    assert await deps.require_superuser(principal) is principal.user


async def test_require_superuser_denies_a_session_non_superuser():
    principal = _session_user(superuser=False)
    with pytest.raises(HTTPException) as caught:
        await deps.require_superuser(principal)
    assert caught.value.status_code == status.HTTP_403_FORBIDDEN
    assert caught.value.detail == SUPERUSER_ACCESS_REQUIRED


@pytest.mark.parametrize(
    ("principal", "detail"),
    [
        (_key_user(superuser=False), "deployment administration is not available to API keys"),
        (_key_user(superuser=True), "deployment administration is not available to API keys"),
        (_session_user(superuser=False), SUPERUSER_ACCESS_REQUIRED),
    ],
)
def test_gate_raises_one_403_per_kind_of_denied_caller(principal: AuthPrincipal, detail: str):
    with pytest.raises(HTTPException) as caught:
        deps.require_deployment_admin(principal)
    assert caught.value.status_code == status.HTTP_403_FORBIDDEN
    assert caught.value.detail == detail


def test_superuser_detail_is_shared_with_the_service_layer():
    # #1090: the session-superuser denial is answered with one phrase, bound to
    # a single constant imported by both the gate and the service re-check.
    assert profiles_service.SUPERUSER_ACCESS_REQUIRED is SUPERUSER_ACCESS_REQUIRED
    assert deps.SUPERUSER_ACCESS_REQUIRED is SUPERUSER_ACCESS_REQUIRED
