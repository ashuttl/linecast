"""The scripts in scripts/, and the package's own functions, still find
what they import from linecast.

A script is run by hand, now and then, so a rename in the package can
leave one broken for months with no test to notice: preview_radar.py
imported a constant that was renamed in July.  This resolves every
linecast name each script imports, at the top or inside a function,
without running any of them.
"""

import ast
import importlib
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SRC = Path(__file__).resolve().parent.parent / "src"


def _linecast_imports(root=SCRIPTS):
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "linecast":
                for alias in node.names:
                    yield path, node.lineno, node.module, alias.name
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "linecast":
                        yield path, node.lineno, alias.name, None


def _missing(root):
    missing = []
    for path, line, module, name in _linecast_imports(root):
        where = f"{path.relative_to(root.parent)}:{line}"
        try:
            found = importlib.import_module(module)
        except ImportError as exc:
            missing.append(f"{where}: {module} ({exc})")
            continue
        if name in (None, "*") or hasattr(found, name):
            continue
        try:
            importlib.import_module(f"{module}.{name}")
        except ImportError:
            missing.append(f"{where}: {module}.{name}")
    return missing


def test_every_linecast_name_a_script_imports_exists():
    missing = _missing(SCRIPTS)
    assert not missing, "scripts import what linecast no longer has: " + "; ".join(missing)


def test_every_linecast_name_the_package_imports_exists():
    # An import inside a function runs only when the function does, so a
    # name moved elsewhere can be left behind there with nothing to fail
    # until a user takes that path.
    missing = _missing(SRC)
    assert not missing, "linecast imports what it no longer has: " + "; ".join(missing)
