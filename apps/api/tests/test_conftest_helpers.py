"""Contract of the shared conftest helpers.

`expire_invitation` must fail a test that hands it a stale invitation id with
an AssertionError naming the row, not an AttributeError raised while assigning
`expires_at` on the missing row. A malformed id is rejected by the UUID column
type before the helper's guard can matter, so the stale case uses a
well-formed id that simply does not exist.
"""

import pytest

from tests.conftest import expire_invitation

_STALE_ID = "00000000-0000-0000-0000-000000000000"


async def test_expire_invitation_rejects_stale_id():
    with pytest.raises(AssertionError, match=_STALE_ID):
        await expire_invitation(_STALE_ID)
