"""db-squash.sh must lint the baseline with the dev extra and fail loudly.

`ruff` is a dev extra only, so `uv run ruff` cannot spawn until the extra is
synced. Silenced with `|| true` and `>/dev/null`, that spawn failure let the
squash report PASS and ship an unformatted baseline.
"""

import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "db-squash.sh"


def _ruff_invocations() -> list[str]:
    lines = SCRIPT.read_text(encoding="utf-8").splitlines()
    return [line for line in lines if line.strip().startswith("uv run") and " ruff" in line]


def test_ruff_runs_with_the_dev_extra():
    invocations = _ruff_invocations()
    assert invocations, "no `uv run ... ruff` invocation found in db-squash.sh"
    for line in invocations:
        assert "--extra dev" in line, f"ruff is a dev extra, it cannot spawn without it: {line}"


def test_ruff_failure_is_not_silenced():
    invocations = _ruff_invocations()
    assert invocations, "no `uv run ... ruff` invocation found in db-squash.sh"
    for line in invocations:
        assert not re.search(r"\|\|\s*true|>\s*/dev/null", line), f"silent ruff step: {line}"
