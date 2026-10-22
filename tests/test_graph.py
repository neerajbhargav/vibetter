"""The static dependency graph and its deterministic layout."""

from __future__ import annotations

import random
from pathlib import Path

import vibetter
from vibetter.graph import MAX_NODES, blueprint, import_graph
from vibetter.index import CodebaseIndex


def shop_files(shop: Path) -> dict[str, str]:
    index = CodebaseIndex(shop)
    index.build()
    return index.files


EXPECTED = {
    ("cli.py", "shop/api.py"),
    ("cli.py", "shop/models.py"),
    ("shop/api.py", "shop/cart.py"),
    ("shop/api.py", "shop/pricing.py"),  # from . import pricing
    ("shop/api.py", "shop/legacy.py"),
    ("shop/api.py", "shop/models.py"),
    ("shop/cart.py", "shop/models.py"),
    ("shop/cart.py", "shop/pricing.py"),
    ("shop/pricing.py", "shop/models.py"),
    ("shop/report.py", "shop/models.py"),
    ("shop/legacy.py", "shop/api.py"),  # a lazy import inside a function
    ("web/src/main.ts", "web/src/App.vue"),
    ("web/src/App.vue", "web/src/components/CartView.vue"),
    ("web/src/App.vue", "web/src/lib/format.ts"),  # @/ alias
    ("web/src/components/CartView.vue", "web/src/lib/format.ts"),
    ("web/src/components/CartView.vue", "web/src/lib/api.js"),
    ("web/src/lib/api.js", "web/src/lib/format.ts"),
}


def test_shop_edges_are_exactly_the_real_imports(shop: Path):
    nodes, edges = import_graph(shop_files(shop))
    assert set(edges) == EXPECTED
    assert "README.md" not in nodes
    assert "shop/__init__.py" in nodes


def test_graph_is_deterministic_regardless_of_file_order(shop: Path):
    files = shop_files(shop)
    items = list(files.items())
    random.Random(7).shuffle(items)
    assert blueprint(files) == blueprint(dict(items))


def test_cycle_edge_is_marked_and_layers_follow_imports(shop: Path):
    graph = blueprint(shop_files(shop))
    cycles = [e for e in graph["edges"] if e.get("label") == "cycle"]
    assert len(cycles) == 1
    assert {cycles[0]["source"], cycles[0]["target"]} == {"shop/api.py", "shop/legacy.py"}
    y = {n["id"]: n["position"]["y"] for n in graph["nodes"]}
    assert y["cli.py"] == 0
    assert y["cli.py"] < y["shop/api.py"] < y["shop/cart.py"] < y["shop/pricing.py"]
    assert y["shop/pricing.py"] < y["shop/models.py"]
    positions = [(n["position"]["x"], n["position"]["y"]) for n in graph["nodes"]]
    assert len(set(positions)) == len(positions)
    kinds = {n["id"]: n["type"] for n in graph["nodes"]}
    assert kinds["cli.py"] == "input" and kinds["shop/models.py"] == "output"


def test_vibetter_own_imports():
    src = Path(vibetter.__file__).parent
    files = {f"src/vibetter/{p.name}": p.read_text() for p in src.glob("*.py")}
    _, edges = import_graph(files)
    for target in ("retrieve", "cite", "graph", "index", "providers", "trace"):
        assert ("src/vibetter/server.py", f"src/vibetter/{target}.py") in edges
    assert ("src/vibetter/cli.py", "src/vibetter/server.py") in edges
    assert ("src/vibetter/graph.py", "src/vibetter/retrieve.py") in edges
    # from . import __version__, cite, ...: __version__ lives in the package itself.
    assert ("src/vibetter/server.py", "src/vibetter/__init__.py") in edges


def test_regression_from_import_mixing_submodules_and_names():
    # Once one name was a submodule, the other names' module was dropped from the graph.
    files = {
        "pkg/__init__.py": "VERSION = 1\n",
        "pkg/a.py": "",
        "pkg/b.py": "from . import VERSION, a\n",
        "main.py": "from pkg import a, VERSION\n",
        "only_sub.py": "from pkg import a\n",
    }
    _, edges = import_graph(files)
    assert ("pkg/b.py", "pkg/__init__.py") in edges and ("pkg/b.py", "pkg/a.py") in edges
    assert ("main.py", "pkg/__init__.py") in edges and ("main.py", "pkg/a.py") in edges
    assert ("only_sub.py", "pkg/a.py") in edges
    assert ("only_sub.py", "pkg/__init__.py") not in edges


def test_large_graph_keeps_the_best_connected_files():
    files = {f"pkg/m{i:03}.py": "import os\n" for i in range(MAX_NODES + 50)}
    files["pkg/__init__.py"] = ""
    files["pkg/hub.py"] = "".join(f"from . import m{i:03}\n" for i in range(10))
    graph = blueprint(files)
    ids = {n["id"] for n in graph["nodes"]}
    assert len(ids) == MAX_NODES
    assert "pkg/hub.py" in ids
    assert graph["stats"]["files_left_out"] == len(files) - MAX_NODES
