"""The `make`-less guard in test_node_floor must skip only the tests that shell out.

The skip is exercised by exec'ing that module's source with `shutil.which`
patched to None, so it runs on machines that do have make. Issues #1238 / #1239.
"""

import shutil
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().with_name("test_node_floor.py")
FLOOR_CHECK = "test_makefile_floor_matches_engines"


@pytest.fixture(autouse=True)
async def _clean_db():
    """This suite only execs a module and reads two files, never the API."""
    yield


def _exec_without_make(monkeypatch):
    """Exec that module with `shutil.which("make")` returning None.

    Returns the module namespace plus the BaseException the exec raised, if any:
    `pytest.skip(..., allow_module_level=True)` raises `Skipped`, a BaseException.
    """
    real_which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "make" else real_which(name))
    namespace = {"__name__": "test_node_floor_guard", "__file__": str(MODULE_PATH)}
    code = compile(MODULE_PATH.read_text(), str(MODULE_PATH), "exec")
    try:
        exec(code, namespace)
    except pytest.skip.Exception as exc:
        return namespace, exc
    return namespace, None


def _skipif_conditions(namespace, name):
    """The positional conditions of the test's skipif marks, None where there is none."""
    marks = getattr(namespace[name], "pytestmark", [])
    return [mark.args[0] if mark.args else None for mark in marks if mark.name == "skipif"]


def _shell_out_tests(namespace):
    """Every test in the module but the one that only reads files, derived not listed.

    ponytail: keyed on "not the floor check", because today the only file-only test is
    that one. A future file-only test would be over-skipped until it gets an exemption.
    """
    return sorted(n for n in namespace if n.startswith("test_") and n != FLOOR_CHECK)


def test_import_survives_without_make(monkeypatch):
    """Importing the module must not skip: it holds a test that needs no make."""
    _namespace, exc = _exec_without_make(monkeypatch)
    assert exc is None, f"module raised {exc!r} when make is absent"


def test_floor_check_is_not_marked(monkeypatch):
    """test_makefile_floor_matches_engines only reads files, so it carries no skip mark."""
    namespace, _exc = _exec_without_make(monkeypatch)
    function = namespace[FLOOR_CHECK]
    skips = [m for m in getattr(function, "pytestmark", []) if m.name in ("skip", "skipif")]
    assert skips == [], f"floor check carries a skip mark: {skips}"


def test_floor_check_passes_without_make(monkeypatch):
    namespace, _exc = _exec_without_make(monkeypatch)
    namespace[FLOOR_CHECK]()


def test_shell_out_tests_are_marked(monkeypatch):
    """Every test that runs `make check-node` must skip when make is absent."""
    namespace, exc = _exec_without_make(monkeypatch)
    assert exc is None, f"module raised {exc!r} when make is absent"
    shell_out = _shell_out_tests(namespace)
    assert shell_out, "found no shell-out tests: did test_node_floor lose its make callers?"
    unmarked = [n for n in shell_out if True not in _skipif_conditions(namespace, n)]
    assert unmarked == [], f"tests that shell out to make but carry no requires_make: {unmarked}"


def test_check_node_guard_is_assertion_not_type_error(monkeypatch, tmp_path):
    """#826: dropping the guard must raise a readable AssertionError, not a TypeError."""
    namespace, _exc = _exec_without_make(monkeypatch)
    assert namespace["MAKE"] is None
    with pytest.raises(AssertionError):
        namespace["_check_node"](tmp_path, "22.18.0")
