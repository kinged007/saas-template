"""The structural tests must not decode files with the process locale.

`read_text()` and `subprocess.run(text=True)` both decode with the locale's
encoding, so on a C locale the tests below die with `UnicodeDecodeError` before
reaching the assertion they exist to make. GitHub runners are UTF-8; a
developer or a self-hosted runner on a C locale sees failures unrelated to the
rule being checked. Pass `encoding=` instead.
"""

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def _locale_decoded_calls() -> list[str]:
    found = []
    for path in sorted(TESTS.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            kwargs = {kw.arg for kw in node.keywords}
            callee = ast.unparse(node.func)
            if callee.endswith("read_text") and "encoding" not in kwargs:
                found.append(f"{path.name}:{node.lineno} read_text() without encoding=")
            elif callee.endswith("run") and kwargs & {"text", "universal_newlines"}:
                found.append(f"{path.name}:{node.lineno} subprocess text=True without encoding=")
    return found


def test_reads_are_utf8_under_an_ascii_locale():
    assert _locale_decoded_calls() == []
