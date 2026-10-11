"""The `make`-less guard in test_node_floor must skip only the tests that shell out.

The skip is exercised by exec'ing that module's source with `shutil.which`
patched to None, so it runs on machines that do have make. Issues #1238 / #1239.
"""

import shutil
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().with_name("test_node_floor.py")
SHELL_OUT_TESTS = [
    "test_warns_below_floor",
    "test_quiet_at_or_above_floor",
    "test_unparseable_version_is_silent",
    "test_silent_without_node",
]


def _exec_without_make(monkeypatch):
    """Exec that module with `shutil.which("make")` returning None.

    Returns the module namespace plus the BaseException the exec raised, if any:
    `pytest.skip(..., allow_module_level=True)` raises `Skipped`, a BaseException.
    """
    monkeypatch.setattr(shutil, "which", lambda name: None)
    namespace = {"__name__": "test_node_floor_guard", "__file__": str(MODULE_PATH)}
    code = compile(MODULE_PATH.read_text(), str(MODULE_PATH), "exec")
    try:
        exec(code, namespace)  # noqa: S102
    except BaseException as exc:  # noqa: BLE001
        return namespace, exc
    return namespace, None


def _skipif_conditions(monkeypatch, name):
    namespace, _exc = _exec_without_make(monkeypatch)
    function = namespace[name]
    marks = getattr(function, "pytestmark", [])
    return [mark.args[0] for mark in marks if mark.name == "skipif"]


def test_import_survives_without_make(monkeypatch):
    """Importing the module must not skip: it holds a test that needs no make."""
    _namespace, exc = _exec_without_make(monkeypatch)
    assert exc is None, f"module raised {exc!r} when make is absent"


def test_floor_check_is_not_marked(monkeypatch):
    """test_makefile_floor_matches_engines only reads files, so it carries no marker."""
    namespace, _exc = _exec_without_make(monkeypatch)
    function = namespace["test_makefile_floor_matches_engines"]
    assert getattr(function, "pytestmark", []) == []


def test_floor_check_passes_without_make(monkeypatch):
    namespace, _exc = _exec_without_make(monkeypatch)
    namespace["test_makefile_floor_matches_engines"]()


@pytest.mark.parametrize("name", SHELL_OUT_TESTS)
def test_shell_out_tests_are_marked(monkeypatch, name):
    """The four tests that run `make check-node` must skip when make is absent."""
    assert True in _skipif_conditions(monkeypatch, name)


def test_check_node_guard_is_assertion_not_type_error(monkeypatch, tmp_path):
    """#826: dropping the guard must raise a readable AssertionError, not a TypeError."""
    namespace, _exc = _exec_without_make(monkeypatch)
    assert namespace["MAKE"] is None
    with pytest.raises(AssertionError):
        namespace["_check_node"](tmp_path, "22.18.0")
