"""The dependency graph, from static analysis only.

Python imports come from `ast`, with relative imports and package roots
resolved the way Python resolves them. JS, TS and Vue imports come from a
regex over `import`, `export ... from`, `require()` and `import()`; relative
paths, `@/` (the nearest `src/`) and extensionless or `/index` specifiers
are resolved. Only edges between indexed files are kept.

The layout is deterministic: cycles are broken by a DFS in path order,
layers are the longest path from entry files, and each layer is ordered by
the mean position of the files that import it. The same files always give
the same graph.
"""

from __future__ import annotations

import ast
import heapq
import posixpath
import re
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from .retrieve import JS_LIKE

PY_LIKE = (".py",)
MAX_NODES = 150
DX, DY = 280, 140
_JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".json")
_JS_IMPORT = re.compile(
    r"""\b(?:import|export)\s[^'"`;]*?\bfrom\s*['"]([^'"\n]+)['"]"""
    r"""|\bimport\s*['"]([^'"\n]+)['"]"""
    r"""|\b(?:require|import)\s*\(\s*['"]([^'"\n]+)['"]\s*\)"""
)


def _parts(directory: str) -> list[str]:
    return [p for p in directory.split("/") if p]


def _module_file(base: list[str], dotted: str, files: Mapping[str, Any]) -> str | None:
    rel = "/".join(base + [p for p in dotted.split(".") if p])
    for candidate in (f"{rel}.py", f"{rel}/__init__.py" if rel else "__init__.py"):
        if candidate in files:
            return candidate
    return None


def _package_roots(files: Mapping[str, Any]) -> list[str]:
    """Directories that hold top-level packages, plus the repo root."""
    roots = {""}
    for path in files:
        if posixpath.basename(path) == "__init__.py":
            package = posixpath.dirname(path)
            parent = posixpath.dirname(package)
            if posixpath.join(parent, "__init__.py") not in files:
                roots.add(parent)
    return sorted(roots)


def python_imports(path: str, text: str, files: Mapping[str, Any], roots: list[str]) -> set[str]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set()
    here = posixpath.dirname(path)
    search = list(roots)
    if posixpath.join(here, "__init__.py") not in files:
        search.insert(0, here)  # a script's own directory is on sys.path
    found: set[str] = set()

    def absolute(dotted: str, names: list[str]) -> None:
        for root in search:
            base = _parts(root)
            subs = {_module_file(base, f"{dotted}.{n}", files) for n in names} - {None}
            target = subs or {_module_file(base, dotted, files)} - {None}
            if target:
                found.update(t for t in target if t)
                return

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                absolute(alias.name, [])
        elif isinstance(node, ast.ImportFrom):
            names = [a.name for a in node.names if a.name != "*"]
            if node.level == 0:
                absolute(node.module or "", names)
                continue
            base = _parts(here)
            if node.level - 1 > len(base):
                continue
            base = base[: len(base) - (node.level - 1)]
            module = node.module or ""
            subs = {_module_file(base, f"{module}.{n}" if module else n, files) for n in names} - {
                None
            }
            target = subs or {_module_file(base, module, files)} - {None}
            found.update(t for t in target if t)
    return found


def js_imports(path: str, text: str, files: Mapping[str, Any]) -> set[str]:
    found: set[str] = set()
    for m in _JS_IMPORT.finditer(text):
        spec = m.group(1) or m.group(2) or m.group(3)
        if spec.startswith(("@/", "~/")):
            parts = _parts(posixpath.dirname(path))
            src = next((i for i in range(len(parts), 0, -1) if parts[i - 1] == "src"), None)
            target = posixpath.join("/".join(parts[:src]) if src else "src", spec[2:])
        elif spec.startswith("."):
            target = posixpath.normpath(posixpath.join(posixpath.dirname(path), spec))
        else:
            continue  # a package, not a file in this repo
        stems = [target]
        if target.endswith(".js"):  # TS projects import "./x.js" for x.ts
            stems.append(target[:-3])
        for stem in stems:
            candidates = [
                stem,
                *(stem + e for e in _JS_EXTS),
                *(f"{stem}/index{e}" for e in _JS_EXTS),
            ]
            hit = next((c for c in candidates if c in files), None)
            if hit:
                found.add(hit)
                break
    return found


def import_graph(files: Mapping[str, str]) -> tuple[list[str], list[tuple[str, str]]]:
    """(code files, sorted importer -> imported edges) between indexed files."""
    code = sorted(p for p in files if p.endswith(PY_LIKE + JS_LIKE))
    code_set = set(code)
    roots = _package_roots(files)
    edges: set[tuple[str, str]] = set()
    for path in code:
        if path.endswith(PY_LIKE):
            targets = python_imports(path, files[path], files, roots)
        else:
            targets = js_imports(path, files[path], files)
        edges.update((path, t) for t in targets if t != path and t in code_set)
    return code, sorted(edges)


def _back_edges(nodes: list[str], succ: Mapping[str, list[str]]) -> set[tuple[str, str]]:
    state: dict[str, int] = {}  # 0 on the DFS stack, 1 finished
    back: set[tuple[str, str]] = set()
    for root in nodes:
        if root in state:
            continue
        state[root] = 0
        stack = [(root, iter(succ[root]))]
        while stack:
            node, children = stack[-1]
            for child in children:
                if child not in state:
                    state[child] = 0
                    stack.append((child, iter(succ[child])))
                    break
                if state[child] == 0:
                    back.add((node, child))
            else:
                state[node] = 1
                stack.pop()
    return back


def layout(
    nodes: list[str], edges: list[tuple[str, str]]
) -> tuple[dict[str, tuple[int, int]], set[tuple[str, str]]]:
    """Deterministic layered positions, and the edges that close a cycle."""
    succ: dict[str, list[str]] = {n: [] for n in nodes}
    for u, v in edges:
        succ[u].append(v)
    for children in succ.values():
        children.sort()
    back = _back_edges(nodes, succ)
    dag = [(u, v) for u, v in edges if (u, v) not in back]
    preds: dict[str, list[str]] = defaultdict(list)
    indegree = dict.fromkeys(nodes, 0)
    for u, v in dag:
        preds[v].append(u)
        indegree[v] += 1
    layer = dict.fromkeys(nodes, 0)
    ready = [n for n in nodes if indegree[n] == 0]
    heapq.heapify(ready)
    while ready:
        u = heapq.heappop(ready)
        for v in succ[u]:
            if (u, v) in back:
                continue
            layer[v] = max(layer[v], layer[u] + 1)
            indegree[v] -= 1
            if indegree[v] == 0:
                heapq.heappush(ready, v)
    rows: dict[int, list[str]] = defaultdict(list)
    for n in nodes:
        rows[layer[n]].append(n)
    slot: dict[str, float] = {}
    positions: dict[str, tuple[int, int]] = {}
    for depth in sorted(rows):

        def key(n: str) -> tuple[float, str]:
            placed = [slot[p] for p in preds[n] if p in slot]
            return (sum(placed) / len(placed) if placed else 0.0, n)

        row = sorted(rows[depth], key=key)
        for i, n in enumerate(row):
            slot[n] = i - (len(row) - 1) / 2
            positions[n] = (round(slot[n] * DX), depth * DY)
    return positions, back


def blueprint(files: Mapping[str, str]) -> dict[str, Any]:
    """A Vue Flow graph: nodes are code files, edges point from importer to imported."""
    nodes, edges = import_graph(files)
    dropped = 0
    if len(nodes) > MAX_NODES:
        degree: dict[str, int] = defaultdict(int)
        for u, v in edges:
            degree[u] += 1
            degree[v] += 1
        keep = set(sorted(nodes, key=lambda n: (-degree[n], n))[:MAX_NODES])
        dropped = len(nodes) - len(keep)
        nodes = [n for n in nodes if n in keep]
        edges = [(u, v) for u, v in edges if u in keep and v in keep]
    positions, back = layout(nodes, edges)
    has_in = {v for _, v in edges}
    has_out = {u for u, _ in edges}
    flow_nodes = []
    for n in nodes:
        kind = "default"
        if n in has_out and n not in has_in:
            kind = "input"
        elif n in has_in and n not in has_out:
            kind = "output"
        x, y = positions[n]
        group = n.split("/", 1)[0] if "/" in n else "."
        flow_nodes.append(
            {
                "id": n,
                "type": kind,
                "position": {"x": x, "y": y},
                "data": {"label": n, "group": group},
            }
        )
    flow_edges = []
    for u, v in edges:
        edge: dict[str, Any] = {"id": f"{u}->{v}", "source": u, "target": v}
        if (u, v) in back:
            edge.update(animated=True, label="cycle")
        flow_edges.append(edge)
    stats = {
        "files": len(nodes),
        "edges": len(edges),
        "cycle_edges": len(back),
        "files_left_out": dropped,
        "method": "static imports (ast for Python, regex for JS/TS/Vue)",
    }
    return {"nodes": flow_nodes, "edges": flow_edges, "stats": stats}
