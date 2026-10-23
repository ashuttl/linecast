"""The package's layers: what may import what.

A module may import from its own layer or any layer below, at module
level or inside a function alike (docs/architecture.md, "The layers"):

    0  the base: paths, text, geometry, PNG, the strings
    1  state and the network: the cache, HTTP, settings, the location
    2  the libraries: terminal/, astro/, the tile arithmetic, the runtime
       and the commands' names
    3  the commands: weather/, sunshine/, moon/, sky/, tides/, radar/, maps/
    4  the entry points: the linecast command, completions, link, doctor,
       prose, and settings/

A command may borrow another command's small modules -- moon.phase,
sunshine.solar -- but never its view or live app, which would bring the
whole command with it.  Nothing imports another module at module level
in a cycle.

UPWARD lists the imports that break the rule today, each with the
reason it stands.  A new one fails here, and so does
an entry that no longer occurs, so the list only shrinks.

A name with a leading underscore belongs to its own package.  Another
package imports only public names, whether by `from ... import` or as
an attribute of a module it imported; what more than one package uses
is given a public name in its home module.  PRIVATE_ACROSS lists the
uses that stand today, and shrinks the same way.  Tests may reach into
anything.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "linecast"
COMMANDS = {"weather", "sunshine", "moon", "sky", "tides", "radar", "maps"}
LAYERS = {
    **dict.fromkeys(("__init__", "_paths", "_plaintext", "_geo", "_png", "_i18n", "_log",
                     "_timefmt", "locales"), 0),
    **dict.fromkeys(("_cache", "_http", "_rate_limit", "_config", "_location", "_geocode",
                     "_fanout"), 1),
    **dict.fromkeys(("terminal", "astro", "_xyz", "_commands", "_parsers", "_runtime"), 2),
    **dict.fromkeys(COMMANDS, 3),
    **dict.fromkeys(("__main__", "_completion", "link", "doctor", "prose", "settings"), 4),
}

# (importer, imported module): the upward imports that stand for now.
UPWARD = {
    ("_parsers", "radar.sources"): "kept: radar_parser's choices, asked for lazily",
    ("astro.hours.i18n", "sunshine.i18n"): "kept: the hours line names sunrise and sunset "
                                           "in sunshine's own words; astro/hours is its library",
}

# (importer, imported module): a command reaching another's view or live.
# There are none; a new one fails here.
INTO_A_VIEW = {
}

# (importer, home module.name): a private name used outside its package.
PRIVATE_ACROSS = {
}


# (module, function): what ends the run below the entry points, each with
# the reason it stands.  Everything else raises _log.UserError, and the
# command's main ends the run with it; a command's own main and _main
# may end it themselves.
ENDS_THE_RUN = {
    ("_log", "exits_on_user_error.run"): "the mains' own exit, made from a UserError",
    ("terminal.term", "LiveTerminal.install._exit_on_signal"):
        "SIGTERM, SIGHUP and SIGQUIT become SystemExit so the live view's "
        "finally blocks restore the terminal",
}


def _modules():
    for path in sorted(SRC.rglob("*.py")):
        if "locales" in path.parts:
            continue
        parts = list(path.relative_to(SRC).with_suffix("").parts)
        if parts[-1] == "__init__" and len(parts) > 1:
            parts.pop()
        yield ".".join(parts), path


def _layer(module):
    head = module.split(".")[0]
    assert head in LAYERS, f"{head} has no layer: add it to LAYERS in tests/test_layers.py"
    return LAYERS[head]


def _imports(module, path, top_level_only=False):
    """(line, imported module) for every linecast import in *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = module.split(".") if path.name == "__init__.py" else module.split(".")[:-1]

    def walk(nodes):
        for node in nodes:
            if top_level_only and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            yield node
            yield from walk(ast.iter_child_nodes(node))

    for node in walk(tree.body):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[:len(package) - node.level + 1]
                parent = ".".join(base + ([node.module] if node.module else []))
            elif node.module == "linecast":
                parent = ""
            elif (node.module or "").startswith("linecast."):
                parent = node.module[len("linecast."):]
            else:
                continue
            for alias in node.names:
                # `from linecast.terminal import theme` imports a module
                child = f"{parent}.{alias.name}" if parent else alias.name
                target = child if (SRC / (child.replace(".", "/") + ".py")).exists() \
                    or (SRC / child.replace(".", "/")).is_dir() else parent
                if target:
                    yield node.lineno, target
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("linecast."):
                    yield node.lineno, alias.name[len("linecast."):]


def _is_module(dotted):
    path = SRC / dotted.replace(".", "/")
    return path.with_suffix(".py").exists() or path.is_dir()


def _private(name):
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _private_uses(module, path):
    """(line, home module, name) for each private name *path* takes from
    linecast: by `from ... import`, or as an attribute of a module it
    imported.  A private submodule counts as a private name of its
    package; the top-level modules (_config, _http, ...) are shared on
    purpose and do not."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = module.split(".") if path.name == "__init__.py" else module.split(".")[:-1]
    bound = {}  # a local name for a linecast module -> that module

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[:len(package) - node.level + 1]
                parent = ".".join(base + ([node.module] if node.module else []))
            elif node.module == "linecast":
                parent = ""
            elif (node.module or "").startswith("linecast."):
                parent = node.module[len("linecast."):]
            else:
                continue
            for alias in node.names:
                child = f"{parent}.{alias.name}" if parent else alias.name
                if _is_module(child):
                    bound[alias.asname or alias.name] = child
                if parent and _private(alias.name):
                    yield node.lineno, parent, alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if not alias.name.startswith("linecast."):
                    continue
                target = alias.name[len("linecast."):]
                if alias.asname:
                    bound[alias.asname] = target
                else:
                    bound["linecast"] = ""
                *home, last = target.split(".")
                if home and _private(last):
                    yield node.lineno, ".".join(home), last

    for node in ast.walk(tree):
        # module.name, or package.module.name, read off a module imported above
        if not isinstance(node, ast.Attribute):
            continue
        chain, root = [], node
        while isinstance(root, ast.Attribute):
            chain.insert(0, root.attr)
            root = root.value
        if not isinstance(root, ast.Name) or root.id not in bound:
            continue
        home = bound[root.id]
        for part in chain:
            name = f"{home}.{part}" if home else part
            if not _is_module(name):
                break
            home = name
        else:
            continue
        if home and _private(part) and node.attr == part:
            yield node.lineno, home, part


def test_every_module_has_a_layer():
    for module, _path in _modules():
        _layer(module)


def test_nothing_imports_a_layer_above_its_own():
    found = set()
    for module, path in _modules():
        for _line, target in _imports(module, path):
            if _layer(target) > _layer(module):
                found.add((module, target))
    assert not found - set(UPWARD), (
        "imports a higher layer (see the docstring): " + ", ".join(
            f"{a} -> {b}" for a, b in sorted(found - set(UPWARD))))
    assert not set(UPWARD) - found, (
        "no longer imported; take it off UPWARD: " + ", ".join(
            f"{a} -> {b}" for a, b in sorted(set(UPWARD) - found)))


def test_no_command_reaches_into_anothers_view():
    found = set()
    for module, path in _modules():
        if _layer(module) != 3:
            continue
        for _line, target in _imports(module, path):
            head, last = target.split(".")[0], target.split(".")[-1]
            if head in COMMANDS and head != module.split(".")[0] and last in ("view", "live"):
                found.add((module, target))
    assert found == set(INTO_A_VIEW), (
        f"new: {sorted(found - set(INTO_A_VIEW))}; gone: {sorted(set(INTO_A_VIEW) - found)}")


def test_no_package_takes_anothers_private_names():
    found = {}
    for module, path in _modules():
        for line, home, name in _private_uses(module, path):
            if home.split(".")[0] != module.split(".")[0]:
                found.setdefault((module, f"{home}.{name}"), line)
    new = {key: line for key, line in found.items() if key not in PRIVATE_ACROSS}
    assert not new, (
        "uses another package's private name; give it a public one in its home "
        "module (see the docstring): " + ", ".join(
            f"{a}:{line} -> {b}" for (a, b), line in sorted(new.items())))
    assert not set(PRIVATE_ACROSS) - set(found), (
        "no longer used; take it off PRIVATE_ACROSS: " + ", ".join(
            f"{a} -> {b}" for a, b in sorted(set(PRIVATE_ACROSS) - set(found))))


def test_the_private_name_check_sees_each_way_in(tmp_path, monkeypatch):
    """A from-import, a relative one, a private submodule, and a private
    attribute of an imported module are each found; a public name and a
    shared top-level module, imported whole, are not."""
    (tmp_path / "tides").mkdir()
    (tmp_path / "moon").mkdir()
    for name in ("tides/__init__.py", "tides/i18n.py", "tides/_shared.py",
                 "moon/__init__.py", "moon/calendar.py", "_config.py"):
        (tmp_path / name).write_text("")
    source = tmp_path / "moon" / "view.py"
    source.write_text(
        "from linecast.tides.i18n import _ts, ts\n"
        "from linecast.tides import i18n as tides_i18n\n"
        "from linecast.tides import _shared\n"
        "from linecast import _config\n"
        "from .calendar import _grid\n"
        "import linecast.tides.i18n\n"
        "tides_i18n._lookup('x')\n"
        "tides_i18n.lookup('x')\n"
        "linecast.tides.i18n._TABLE\n"
        "_config._load()\n")
    monkeypatch.setitem(globals(), "SRC", tmp_path)
    assert {(home, name) for _line, home, name in _private_uses("moon.view", source)} == {
        ("tides.i18n", "_ts"), ("tides", "_shared"), ("moon.calendar", "_grid"),
        ("tides.i18n", "_lookup"), ("tides.i18n", "_TABLE"), ("_config", "_load")}


def test_no_import_cycle_at_module_level():
    graph = {module: set() for module, _path in _modules()}
    for module, path in _modules():
        for _line, target in _imports(module, path, top_level_only=True):
            if target in graph and target != module:
                graph[module].add(target)
    # Tarjan's strongly connected components
    index, low, stack, on_stack, cycles = {}, {}, [], set(), []

    def visit(v):
        index[v] = low[v] = len(index)
        stack.append(v)
        on_stack.add(v)
        for w in graph[v]:
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            component = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                component.append(w)
                if w == v:
                    break
            if len(component) > 1:
                cycles.append(sorted(component))

    for v in sorted(graph):
        if v not in index:
            visit(v)
    assert not cycles, f"module-level import cycles: {cycles}"


def _exits(path):
    """(the enclosing defs, line) of each sys.exit() and raise SystemExit
    in *path*."""
    found = []

    def visit(node, stack):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(child, stack + (child.name,))
                continue
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "exit"
                    and getattr(child.func.value, "id", None) == "sys"):
                found.append((stack, child.lineno))
            elif isinstance(child, ast.Raise) and child.exc is not None:
                exc = child.exc.func if isinstance(child.exc, ast.Call) else child.exc
                if getattr(exc, "id", None) == "SystemExit":
                    found.append((stack, child.lineno))
            visit(child, stack)

    visit(ast.parse(path.read_text(encoding="utf-8")), ())
    return found


def test_only_a_main_ends_the_run():
    # A library that ends the process ends only the thread when it runs
    # in a worker, and silently; below the entry points a failure the
    # user must act on is a UserError, which the main turns into the exit
    found, stray = set(), []
    for module, path in _modules():
        if _layer(module) == 4:
            continue
        for stack, line in _exits(path):
            if _layer(module) == 3 and {"main", "_main"} & set(stack):
                continue
            key = (module, ".".join(stack))
            if key in ENDS_THE_RUN:
                found.add(key)
            else:
                stray.append(f"{module}:{line}")
    assert not stray, ("ends the run below a main; raise _log.UserError instead: "
                       + ", ".join(stray))
    assert found == set(ENDS_THE_RUN), f"no longer there: {set(ENDS_THE_RUN) - found}"
