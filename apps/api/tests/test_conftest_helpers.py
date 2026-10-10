"""Contract of the shared conftest helpers.

`expire_invitation` must fail a test that hands it a stale invitation id with
an AssertionError naming the row, not an AttributeError raised while assigning
`expires_at` on the missing row. A malformed id is rejected by the UUID column
type before the helper's guard can matter, so the stale case uses a
well-formed id that simply does not exist.

`wait_for` is the one deadline loop the suite's per-test pollers used to carry,
so it must stop at the first satisfied poll (never burn the budget) and return
False instead of hanging when a predicate never turns true.
"""

import asyncio

import pytest

from tests.conftest import expire_invitation, wait_for

_STALE_ID = "00000000-0000-0000-0000-000000000000"


async def test_expire_invitation_rejects_stale_id():
    with pytest.raises(AssertionError, match=_STALE_ID):
        await expire_invitation(_STALE_ID)


async def test_wait_for_stops_at_the_first_satisfied_poll():
    polls = 0

    def satisfied_on_third_poll() -> bool:
        nonlocal polls
        polls += 1
        return polls >= 3

    started = asyncio.get_running_loop().time()
    assert await wait_for(satisfied_on_third_poll, timeout_secs=5, interval=0.01)
    assert polls == 3
    assert asyncio.get_running_loop().time() - started < 0.5


async def test_wait_for_awaits_an_async_predicate():
    async def row() -> str:
        return "audit row"

    assert await wait_for(row, timeout_secs=5, interval=0.01)


async def test_wait_for_returns_false_when_the_predicate_never_satisfies():
    assert not await wait_for(lambda: False, timeout_secs=0.05, interval=0.01)
