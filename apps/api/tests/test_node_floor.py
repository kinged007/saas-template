"""`make check-node` must warn below the Node floor apps/web declares in engines.

Skip shape for missing optional tooling: a `requires_make` marker, so a make-less
runner names the tests that shell out and still collects the file-only test below.
The convention is stated once in `conftest.py`; `allow_module_level=True` there instead
collapsed the whole module into one file-level skip, hiding that test (issue #1238)."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MAKE = shutil.which("make")
requires_make = pytest.mark.skipif(MAKE is None, reason="make not installed")


@pytest.fixture(autouse=True)
async def _clean_db():
    """Override conftest's DB reset: this suite only shells out to make, never the API."""
    yield


def _check_node(tmp_path, version=None):
    """Run `make check-node` with a `node` shim reporting `version` (None: no node at all)."""
    assert MAKE is not None, "requires_make skips every caller when make is absent"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    if version is None:
        path = str(bindir)
    else:
        shim = bindir / "node"
        shim.write_text(f'#!/bin/sh\necho "v{version}"\n')
        shim.chmod(0o755)
        path = f"{bindir}{os.pathsep}{os.environ['PATH']}"
    # Drop what an outer make exports: MAKELEVEL above 0 alone makes the child make
    # print `Entering directory` lines, which is what this file asserts against.
    env = {k: v for k, v in os.environ.items() if k not in {"MAKEFLAGS", "MFLAGS", "MAKELEVEL"}}
    env["PATH"] = path
    return subprocess.run(
        [MAKE, "--no-print-directory", "check-node"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_makefile_floor_matches_engines():
    """The Makefile constants must track apps/web/package.json engines, or the warning lies."""
    engines = json.loads((ROOT / "apps/web/package.json").read_text())["engines"]["node"]
    major, minor = engines.removeprefix(">=").split(".")
    makefile = (ROOT / "Makefile").read_text()
    assert f"WEB_NODE_MAJOR := {major}\n" in makefile
    assert f"WEB_NODE_MINOR := {minor}\n" in makefile


@pytest.mark.parametrize("version", ["18.20.4", "20.11.0", "22.17.9"])
@requires_make
def test_warns_below_floor(tmp_path, version):
    out = _check_node(tmp_path, version)
    assert out.returncode == 0, out.stderr
    assert "22.18" in out.stdout
    assert "apps/web" in out.stdout


@pytest.mark.parametrize("version", ["22.18.0", "24.19.0"])
@requires_make
def test_quiet_at_or_above_floor(tmp_path, version):
    out = _check_node(tmp_path, version)
    assert out.returncode == 0, out.stderr
    assert "warning" not in out.stdout


@pytest.mark.parametrize("version", ["weird", "22.x"])
@requires_make
def test_unparseable_version_is_silent(tmp_path, version):
    out = _check_node(tmp_path, version)
    assert out.returncode == 0, out.stderr
    assert "warning" not in out.stdout
    assert "integer" not in out.stderr


@requires_make
def test_silent_without_node(tmp_path):
    out = _check_node(tmp_path)
    assert out.returncode == 0, out.stderr
    assert out.stdout == ""
