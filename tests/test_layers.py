"""The package's layers: what may import what.

A module may import from its own layer or any layer below, at module
level or inside a function alike (docs/architecture.md, "The layers"):

    0  the base: paths, text, geometry, PNG, the strings
    1  state and the network: the cache, HTTP, settings, the location
    2  the libraries: terminal/, astro/, the runtime and the commands' names
    3  the commands: weather/, sunshine/, moon/, sky/, tides/, radar/, maps/
    4  the entry points: the linecast command, completions, link, doctor,
       prose, and settings/

A command may borrow another command's small modules -- moon.phase,
sunshine.solar -- but never its view or live app, which would bring the
whole command with it.  Nothing imports another module at module level
in a cycle.

UPWARD lists the imports that break the rule today, each with the step
of SNOW-LEOPARD.md that removes it.  A new one fails here, and so does
an entry that no longer occurs, so the list only shrinks.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "linecast"
COMMANDS = {"weather", "sunshine", "moon", "sky", "tides", "radar", "maps"}
LAYERS = {
    **dict.fromkeys(("__init__", "_paths", "_plaintext", "_geo", "_png", "_i18n", "_log",
                     "_timefmt", "locales"), 0),
    **dict.fromkeys(("_cache", "_http", "_rate_limit", "_config", "_location", "_geocode"), 1),
    **dict.fromkeys(("terminal", "astro", "_commands", "_parsers", "_runtime"), 2),
    **dict.fromkeys(COMMANDS, 3),
    **dict.fromkeys(("__main__", "_completion", "link", "doctor", "prose", "settings"), 4),
}

# (importer, imported module): the upward imports that stand for now.
UPWARD = {
    # the unit labels' words, and radar's themes for its parser (kept)
    ("_runtime", "weather.i18n"): "2.4",
    ("_parsers", "radar.sources"): "kept: radar_parser's choices, asked for lazily",
    # shared words move to _i18n and HELP (2.4)
    ("astro.hours.i18n", "sunshine.i18n"): "2.4", ("terminal.help", "maps.i18n"): "2.4",
    # each command's one line moves to the command (2.6)
    **dict.fromkeys((("terminal.oneline", m) for m in (
        "moon.phase", "moon.view", "sky.catalogue", "sky.i18n", "sky.scene", "sky.view",
        "sunshine.hours", "sunshine.i18n", "sunshine.palette", "sunshine.solar",
        "tides.i18n", "weather.cover", "weather.i18n", "weather.style")), "2.6"),
}

# (importer, imported module): a command reaching another's view or live.
# There are none; a new one fails here.
INTO_A_VIEW = {
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
