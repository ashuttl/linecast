"""The scripts in scripts/ still find what they import from linecast.

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


def _linecast_imports():
    for path in sorted(SCRIPTS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "linecast":
                for alias in node.names:
                    yield path, node.lineno, node.module, alias.name
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "linecast":
                        yield path, node.lineno, alias.name, None


def test_every_linecast_name_a_script_imports_exists():
    missing = []
    for path, line, module, name in _linecast_imports():
        where = f"{path.relative_to(SCRIPTS.parent)}:{line}"
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
    assert not missing, "scripts import what linecast no longer has: " + "; ".join(missing)
