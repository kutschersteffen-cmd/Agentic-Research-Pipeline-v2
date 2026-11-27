"""Architecture & import-graph guard for backend/arp/.

Enforces two invariants with a shrinking allowlist (.github/arch_allowlist.json)
that reaches zero by PR 5 of the modular-monolith refactoring:

1. Strict layer DAG & domain isolation:
   - Entrypoints (api, cli, worker, __main__) -> anything
   - runtime -> domains / platform / core / legacy (never entrypoints)
   - domains / legacy -> platform / core / legacy (never entrypoints or runtime)
   - platform -> platform / core (never domains, legacy, runtime, entrypoints)
   - core -> core only
   - domains.<A> -> domains.<B> ONLY via domains.<B>.public (never internals)

2. No new circular dependencies:
   - Neither at the module level nor at the logical package level (Tarjan SCCs).

Any violation already present in the allowlist is permitted temporarily so the
guard can land immediately; ANY new violation fails CI. Deleting or fixing
allowlisted edges always passes and reports how many entries can be pruned.

Usage:
    python3 .github/scripts/arch_guard.py                   # check against allowlist
    python3 .github/scripts/arch_guard.py --strict          # demand zero violations
    python3 .github/scripts/arch_guard.py --update-allowlist
    python3 .github/scripts/arch_guard.py --selftest
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACKAGE_ROOT = REPO_ROOT / "backend" / "arp"
DEFAULT_ALLOWLIST = REPO_ROOT / ".github" / "arch_allowlist.json"

ENTRYPOINT_SUBPACKAGES = frozenset({"api", "cli", "worker", "__main__"})


@dataclass(frozen=True)
class AnalysisResult:
    module_count: int
    layer_violations: list[str]
    module_cycle_edges: list[str]
    package_cycle_edges: list[str]
    module_scc_sizes: list[int]
    package_scc_sizes: list[int]


def discover_modules(package_root: Path) -> dict[str, tuple[Path, bool]]:
    """Map dotted module name -> (file_path, is_package_init)."""
    mods: dict[str, tuple[Path, bool]] = {}
    base = package_root.parent
    for path in sorted(package_root.rglob("*.py")):
        rel = path.relative_to(base).with_suffix("")
        parts = list(rel.parts)
        is_pkg = parts[-1] == "__init__"
        if is_pkg:
            parts = parts[:-1]
        mod = ".".join(parts)
        mods[mod] = (path, is_pkg)
    return mods


def _from_import_targets(
    node: ast.ImportFrom,
    pkg_parts: list[str],
    known_mods: dict[str, tuple[Path, bool]],
    root_pkg: str,
) -> set[str]:
    prefix = f"{root_pkg}."
    if node.level > 0:
        trim = node.level - 1
        if trim > len(pkg_parts):
            return set()
        base = pkg_parts[: len(pkg_parts) - trim]
        if node.module:
            base = base + node.module.split(".")
        module_name = ".".join(base)
    else:
        module_name = node.module or ""

    if not (module_name == root_pkg or module_name.startswith(prefix)):
        return set()

    targets = {module_name}
    for alias in node.names:
        if alias.name != "*":
            cand = f"{module_name}.{alias.name}"
            if cand in known_mods:
                targets.add(cand)
    return targets


def _resolve_known_module(target: str, known_mods: dict[str, tuple[Path, bool]]) -> str:
    cur = target
    while cur and cur not in known_mods:
        cur = cur.rsplit(".", 1)[0] if "." in cur else ""
    return cur


def extract_imports(
    mod: str,
    path: Path,
    is_pkg: bool,
    known_mods: dict[str, tuple[Path, bool]],
    root_pkg: str,
) -> set[str]:
    """Return resolved internal module names imported by `mod`."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    pkg_parts = mod.split(".") if is_pkg else mod.split(".")[:-1]
    raw_targets: set[str] = set()
    prefix = f"{root_pkg}."

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == root_pkg or alias.name.startswith(prefix):
                    raw_targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            raw_targets |= _from_import_targets(node, pkg_parts, known_mods, root_pkg)

    resolved: set[str] = set()
    for target in raw_targets:
        known = _resolve_known_module(target, known_mods)
        if known and known != mod:
            resolved.add(known)
    return resolved


def layer_of(mod: str) -> tuple[str, str | None]:
    """Classify a module into (layer, domain_name_or_none)."""
    parts = mod.split(".")
    if len(parts) == 1:
        return ("root", None)
    if parts[1] in ENTRYPOINT_SUBPACKAGES:
        return ("entrypoint", None)
    if parts[1] == "runtime":
        return ("runtime", None)
    if parts[1] == "core":
        return ("core", None)
    if parts[1] == "platform":
        return ("platform", None)
    if parts[1] == "domains":
        domain = parts[2] if len(parts) >= 3 else None
        return ("domain", domain)
    return ("legacy", None)


def package_key(mod: str) -> str:
    """Logical package grouping for package-level cycle detection."""
    parts = mod.split(".")
    if len(parts) >= 3 and parts[1] in ("domains", "platform"):
        return ".".join(parts[:3])
    if len(parts) >= 2:
        return ".".join(parts[:2])
    return mod


def check_layer_edge(src: str, dst: str) -> str | None:
    """Return a violation rule name if `src -> dst` breaks the layer DAG, else None."""
    src_layer, src_domain = layer_of(src)
    dst_layer, dst_domain = layer_of(dst)

    if src_layer in ("entrypoint", "root") or dst_layer == "root":
        return None
    if dst_layer == "entrypoint":
        return "no_upward_to_entrypoint"
    if dst_layer == "runtime" and src_layer != "runtime":
        return "no_upward_to_runtime"
    if src_layer == "core" and dst_layer != "core":
        return "core_must_be_leaf"
    if src_layer == "platform" and dst_layer not in ("platform", "core"):
        return "platform_cannot_import_domain"
    if (
        src_layer == "domain"
        and dst_layer == "domain"
        and src_domain is not None
        and dst_domain is not None
        and src_domain != dst_domain
    ):
        parts = dst.split(".")
        # Only `arp.domains.<B>` or `arp.domains.<B>.public(.<...>)` is allowed.
        if len(parts) > 3 and parts[3] != "public":
            return "domain_internal_import"
    return None


def tarjan_sccs(graph: dict[str, set[str]]) -> list[list[str]]:
    """Iterative Tarjan strongly-connected components with size > 1."""
    index = 0
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    sccs: list[list[str]] = []

    all_nodes = sorted(set(graph.keys()) | {w for vs in graph.values() for w in vs})
    for start in all_nodes:
        if start in indices:
            continue
        call_stack: list[tuple[str, list[str], int]] = [(start, sorted(graph.get(start, ())), 0)]
        indices[start] = lowlink[start] = index
        index += 1
        stack.append(start)
        on_stack.add(start)

        while call_stack:
            v, neighbors, ni = call_stack[-1]
            if ni < len(neighbors):
                call_stack[-1] = (v, neighbors, ni + 1)
                w = neighbors[ni]
                if w not in indices:
                    indices[w] = lowlink[w] = index
                    index += 1
                    stack.append(w)
                    on_stack.add(w)
                    call_stack.append((w, sorted(graph.get(w, ())), 0))
                elif w in on_stack:
                    lowlink[v] = min(lowlink[v], indices[w])
            else:
                call_stack.pop()
                if call_stack:
                    parent = call_stack[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[v])
                if lowlink[v] == indices[v]:
                    comp: list[str] = []
                    while True:
                        w = stack.pop()
                        on_stack.remove(w)
                        comp.append(w)
                        if w == v:
                            break
                    if len(comp) > 1:
                        sccs.append(sorted(comp))

    sccs.sort(key=lambda c: (-len(c), c[0]))
    return sccs


def analyze(package_root: Path) -> AnalysisResult:
    root_pkg = package_root.name
    mods = discover_modules(package_root)
    adj: dict[str, set[str]] = {
        mod: extract_imports(mod, path, is_pkg, mods, root_pkg)
        for mod, (path, is_pkg) in mods.items()
    }

    layer_violations: list[str] = []
    for src in sorted(adj):
        for dst in sorted(adj[src]):
            rule = check_layer_edge(src, dst)
            if rule is not None:
                layer_violations.append(f"{rule}: {src} -> {dst}")

    mod_sccs = tarjan_sccs(adj)
    mod_cycle_edges: list[str] = []
    for comp in mod_sccs:
        members = set(comp)
        for src in comp:
            for dst in sorted(adj.get(src, ())):
                if dst in members:
                    mod_cycle_edges.append(f"{src} -> {dst}")

    pkg_adj: dict[str, set[str]] = defaultdict(set)
    for src, dsts in adj.items():
        ps = package_key(src)
        for dst in dsts:
            pd = package_key(dst)
            if ps != pd:
                pkg_adj[ps].add(pd)

    pkg_sccs = tarjan_sccs(pkg_adj)
    pkg_cycle_edges: list[str] = []
    for comp in pkg_sccs:
        members = set(comp)
        for src in comp:
            for dst in sorted(pkg_adj.get(src, ())):
                if dst in members:
                    pkg_cycle_edges.append(f"{src} -> {dst}")

    return AnalysisResult(
        module_count=len(mods),
        layer_violations=sorted(set(layer_violations)),
        module_cycle_edges=sorted(set(mod_cycle_edges)),
        package_cycle_edges=sorted(set(pkg_cycle_edges)),
        module_scc_sizes=[len(c) for c in mod_sccs],
        package_scc_sizes=[len(c) for c in pkg_sccs],
    )


def load_allowlist(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {"layer_violations": [], "module_cycle_edges": [], "package_cycle_edges": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "layer_violations": list(data.get("layer_violations", [])),
        "module_cycle_edges": list(data.get("module_cycle_edges", [])),
        "package_cycle_edges": list(data.get("package_cycle_edges", [])),
    }


def write_allowlist(path: Path, result: AnalysisResult) -> None:
    payload = {
        "_comment": (
            "Shrinking baseline of pre-existing architecture & cycle violations. "
            "Do not add new entries manually; shrink with "
            "`python3 .github/scripts/arch_guard.py --update-allowlist` as PRs 2-5 clean them up."
        ),
        "layer_violations": result.layer_violations,
        "module_cycle_edges": result.module_cycle_edges,
        "package_cycle_edges": result.package_cycle_edges,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def check_against_allowlist(
    result: AnalysisResult,
    allowlist: dict[str, list[str]],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return (new_violations, resolved_allowlist_entries) per category."""
    current = {
        "layer_violations": set(result.layer_violations),
        "module_cycle_edges": set(result.module_cycle_edges),
        "package_cycle_edges": set(result.package_cycle_edges),
    }
    new_bad: dict[str, list[str]] = {}
    resolved: dict[str, list[str]] = {}
    for key, cur_set in current.items():
        allowed = set(allowlist.get(key, []))
        new_bad[key] = sorted(cur_set - allowed)
        resolved[key] = sorted(allowed - cur_set)
    return new_bad, resolved


def _write_tree(base: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return base / "arp"


def selftest() -> None:
    # 1. Clean modular-monolith DAG passes with zero violations.
    with tempfile.TemporaryDirectory() as d:
        root = _write_tree(
            Path(d),
            {
                "arp/__init__.py": "",
                "arp/core/__init__.py": "",
                "arp/core/errors.py": "class AppError(Exception): pass\n",
                "arp/platform/__init__.py": "",
                "arp/platform/db.py": "from arp.core.errors import AppError\n",
                "arp/domains/__init__.py": "",
                "arp/domains/alpha/__init__.py": "",
                "arp/domains/alpha/public.py": "from arp.domains.alpha.service import run\n",
                "arp/domains/alpha/service.py": "from arp.platform.db import AppError\n",
                "arp/domains/beta/__init__.py": "",
                "arp/domains/beta/service.py": "from arp.domains.alpha.public import run\n",
                "arp/runtime/__init__.py": "",
                "arp/runtime/container.py": "from arp.domains.beta.service import run\n",
                "arp/api/__init__.py": "",
                "arp/api/main.py": "from arp.runtime.container import run\n",
            },
        )
        res = analyze(root)
        assert not res.layer_violations, res.layer_violations
        assert not res.module_cycle_edges, res.module_cycle_edges
        assert not res.package_cycle_edges, res.package_cycle_edges

    # 2. Layer & domain isolation violations are caught (including relative imports).
    with tempfile.TemporaryDirectory() as d:
        root = _write_tree(
            Path(d),
            {
                "arp/__init__.py": "",
                "arp/api/__init__.py": "",
                "arp/api/deps.py": "",
                "arp/runtime/__init__.py": "",
                "arp/runtime/container.py": "from arp.api import deps\n",
                "arp/core/__init__.py": "",
                "arp/core/errors.py": "from arp.platform import db\n",
                "arp/platform/__init__.py": "",
                "arp/platform/db.py": "from arp.domains.alpha import service\n",
                "arp/domains/__init__.py": "",
                "arp/domains/alpha/__init__.py": "",
                "arp/domains/alpha/service.py": "from ...api import deps\nfrom arp.runtime import container\n",
                "arp/domains/beta/__init__.py": "",
                "arp/domains/beta/service.py": "from arp.domains.alpha.service import deps\n",
            },
        )
        res = analyze(root)
        rules = {v.split(":")[0] for v in res.layer_violations}
        assert rules == {
            "no_upward_to_entrypoint",
            "no_upward_to_runtime",
            "core_must_be_leaf",
            "platform_cannot_import_domain",
            "domain_internal_import",
        }, res.layer_violations

    # 3. Module and package cycles are caught, and shrinking allowlist works.
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        root = _write_tree(
            base,
            {
                "arp/__init__.py": "",
                "arp/pkg_a/__init__.py": "",
                "arp/pkg_a/one.py": "from arp.pkg_b import two\n",
                "arp/pkg_b/__init__.py": "",
                "arp/pkg_b/two.py": "from arp.pkg_a import one\n",
            },
        )
        res = analyze(root)
        assert res.module_cycle_edges == ["arp.pkg_a.one -> arp.pkg_b.two", "arp.pkg_b.two -> arp.pkg_a.one"], res
        assert res.package_cycle_edges == ["arp.pkg_a -> arp.pkg_b", "arp.pkg_b -> arp.pkg_a"], res

        allow_path = base / "allow.json"
        write_allowlist(allow_path, res)
        new_bad, resolved = check_against_allowlist(res, load_allowlist(allow_path))
        assert not any(new_bad.values()), new_bad
        assert not any(resolved.values()), resolved

        # Breaking the cycle passes and reports resolved allowlist entries.
        (root / "pkg_b" / "two.py").write_text("x = 1\n", encoding="utf-8")
        res2 = analyze(root)
        new_bad2, resolved2 = check_against_allowlist(res2, load_allowlist(allow_path))
        assert not any(new_bad2.values()), new_bad2
        assert len(resolved2["module_cycle_edges"]) == 2, resolved2

        # Introducing a new upward import fails even with old allowlist.
        (root / "api").mkdir()
        (root / "api" / "__init__.py").write_text("", encoding="utf-8")
        (root / "pkg_a" / "one.py").write_text("import arp.api\n", encoding="utf-8")
        res3 = analyze(root)
        new_bad3, _ = check_against_allowlist(res3, load_allowlist(allow_path))
        assert new_bad3["layer_violations"] == ["no_upward_to_entrypoint: arp.pkg_a.one -> arp.api"], new_bad3

    print("arch_guard selftest ok")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enforce arp architecture DAG and prevent new import cycles.")
    parser.add_argument("--root", type=Path, default=DEFAULT_PACKAGE_ROOT, help="Path to backend/arp")
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST, help="Path to arch_allowlist.json")
    parser.add_argument("--strict", action="store_true", help="Ignore allowlist and fail on any violation")
    parser.add_argument("--update-allowlist", action="store_true", help="Write current violations to allowlist file")
    parser.add_argument("--selftest", action="store_true", help="Run built-in self-tests and exit")
    args = parser.parse_args(argv)

    if args.selftest:
        selftest()
        return 0

    result = analyze(args.root)
    if args.update_allowlist:
        write_allowlist(args.allowlist, result)
        print(
            f"Updated {args.allowlist}: "
            f"{len(result.layer_violations)} layer violations, "
            f"{len(result.module_cycle_edges)} module cycle edges, "
            f"{len(result.package_cycle_edges)} package cycle edges."
        )
        return 0

    allowlist = (
        {"layer_violations": [], "module_cycle_edges": [], "package_cycle_edges": []}
        if args.strict
        else load_allowlist(args.allowlist)
    )
    new_bad, resolved = check_against_allowlist(result, allowlist)

    print(
        f"arch_guard scanned {result.module_count} modules: "
        f"{len(result.layer_violations)} layer violations, "
        f"{len(result.module_cycle_edges)} module cycle edges (SCCs={result.module_scc_sizes}), "
        f"{len(result.package_cycle_edges)} package cycle edges (SCCs={result.package_scc_sizes})."
    )

    total_resolved = sum(len(v) for v in resolved.values())
    if total_resolved:
        print(
            f"Progress: {total_resolved} allowlisted violation(s) have been fixed! "
            "Run `python3 .github/scripts/arch_guard.py --update-allowlist` to shrink the baseline."
        )

    total_new = sum(len(v) for v in new_bad.values())
    if total_new:
        print(f"\nFAIL: {total_new} new architecture violation(s) introduced:")
        for category, items in new_bad.items():
            if not items:
                continue
            print(f"\n[{category}] ({len(items)} new):")
            for item in items[:50]:
                print(f"  {item}")
            if len(items) > 50:
                print(f"  ... and {len(items) - 50} more")
        return 1

    print("arch_guard ok (no new violations).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
