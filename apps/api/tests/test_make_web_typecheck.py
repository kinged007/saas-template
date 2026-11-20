"""`make web-typecheck` must run the real TypeScript compiler, never a registry
package that `npx` fetches when apps/web/node_modules is absent."""

import shutil
import subprocess
from pathlib import Path

MAKEFILE = Path(__file__).resolve().parents[3] / "Makefile"


def _run_typecheck(root: Path) -> subprocess.CompletedProcess[str]:
    shutil.copy(MAKEFILE, root / "Makefile")
    (root / "apps" / "web").mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        ["make", "web-typecheck"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_missing_tsc_fails_and_names_web_install(tmp_path):
    proc = _run_typecheck(tmp_path)
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, f"expected a hard failure, got:\n{output}"
    assert "make web-install" in output


def test_present_tsc_runs_the_compiler(tmp_path):
    tsc = tmp_path / "apps" / "web" / "node_modules" / ".bin" / "tsc"
    tsc.parent.mkdir(parents=True)
    tsc.write_text('#!/bin/sh\necho "real tsc ran $@"\n')
    tsc.chmod(0o755)

    proc = _run_typecheck(tmp_path)
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    assert "real tsc ran -p tsconfig.json --noEmit" in output
