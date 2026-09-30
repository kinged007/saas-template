"""`make check-node` must warn below the Node floor apps/web declares in engines."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _check_node(tmp_path, version):
    """Run `make check-node` with a `node` shim reporting `version`."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shim = bindir / "node"
    shim.write_text(f'#!/bin/sh\necho "v{version}"\n')
    shim.chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run(["make", "check-node"], cwd=ROOT, env=env, capture_output=True, text=True)


@pytest.mark.parametrize("version", ["18.20.4", "20.11.0", "22.17.9"])
def test_warns_below_floor(tmp_path, version):
    # floor comes from apps/web/package.json engines
    out = _check_node(tmp_path, version)
    assert out.returncode == 0, out.stderr
    assert "22.18" in out.stdout
    assert "apps/web" in out.stdout


@pytest.mark.parametrize("version", ["22.18.0", "24.19.0"])
def test_quiet_at_or_above_floor(tmp_path, version):
    out = _check_node(tmp_path, version)
    assert out.returncode == 0, out.stderr
    assert "warning" not in out.stdout
