"""`make check-node` must warn below the Node floor apps/web declares in engines."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MAKE = shutil.which("make") or pytest.skip("make not installed", allow_module_level=True)


@pytest.fixture(autouse=True)
async def _clean_db():
    """Override conftest's DB reset: this suite only shells out to make, never the API."""
    yield


def _check_node(tmp_path, version=None):
    """Run `make check-node` with a `node` shim reporting `version` (None: no node at all)."""
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
        encoding="utf-8",
    )


def test_makefile_floor_matches_engines():
    """The Makefile constants must track apps/web/package.json engines, or the warning lies."""
    package = json.loads((ROOT / "apps/web/package.json").read_text(encoding="utf-8"))
    major, minor = package["engines"]["node"].removeprefix(">=").split(".")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert f"WEB_NODE_MAJOR := {major}\n" in makefile
    assert f"WEB_NODE_MINOR := {minor}\n" in makefile


@pytest.mark.parametrize("version", ["18.20.4", "20.11.0", "22.17.9"])
def test_warns_below_floor(tmp_path, version):
    out = _check_node(tmp_path, version)
    assert out.returncode == 0, out.stderr
    assert "22.18" in out.stdout
    assert "apps/web" in out.stdout


@pytest.mark.parametrize("version", ["22.18.0", "24.19.0"])
def test_quiet_at_or_above_floor(tmp_path, version):
    out = _check_node(tmp_path, version)
    assert out.returncode == 0, out.stderr
    assert "warning" not in out.stdout


@pytest.mark.parametrize("version", ["weird", "22.x"])
def test_unparseable_version_is_silent(tmp_path, version):
    out = _check_node(tmp_path, version)
    assert out.returncode == 0, out.stderr
    assert "warning" not in out.stdout
    assert "integer" not in out.stderr


def test_silent_without_node(tmp_path):
    out = _check_node(tmp_path)
    assert out.returncode == 0, out.stderr
    assert out.stdout == ""
