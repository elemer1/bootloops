"""Minimal capacity ledger: can the asset's value fit through the capped baskets a path uses?

Each capped investment step must carry the full asset value, drawn from the basket pools
its permitting rules give access to; a pool shared by several rules or steps (e.g. the
Available Amount builder basket) is consumed cumulatively. Feasibility is a bipartite
max-flow (steps -> pools) in exact integers (US dollars). Uncapped steps need no capacity.
"""
from __future__ import annotations

from collections import defaultdict


def _maxflow(cap, s, t):
    flow = 0
    while True:
        parent = {s: None}
        q = [s]
        while q and t not in parent:
            u = q.pop(0)
            for v, c in cap[u].items():
                if c > 0 and v not in parent:
                    parent[v] = u
                    q.append(v)
        if t not in parent:
            return flow
        f, v = None, t
        while parent[v] is not None:
            u = parent[v]
            f = cap[u][v] if f is None else min(f, cap[u][v])
            v = u
        v = t
        while parent[v] is not None:
            u = parent[v]
            cap[u][v] -= f
            cap[v][u] += f
            v = u
        flow += f


def check_path(path, value, pools, rule_pools, category="investments"):
    """Returns {"feasible": bool, "demand": int, "routed": int, "steps": [...], "unpriced": [...]}.

    pools: {pool: amount}; rule_pools: {rule id: [pool, ...]}. A capped rule with no pool
    mapping is 'unpriced' and contributes no capacity (conservative)."""
    cap = defaultdict(lambda: defaultdict(int))
    demand, steps, unpriced = 0, [], set()
    for i, st in enumerate(path):
        if st["capacity"].get(category) != "capped":
            steps.append({"step": i, "needs": 0})
            continue
        node = f"step{i}"
        cap["S"][node] = value
        demand += value
        reach = set()
        for rid in (st.get("designated") or st["used"].get(category, [])):
            for p in rule_pools.get(rid, []):
                reach.add(p)
            if rid not in rule_pools:
                unpriced.add(rid)
        for p in reach:
            cap[node][f"pool:{p}"] = value
        steps.append({"step": i, "needs": value, "pools": sorted(reach)})
    for p, amt in pools.items():
        cap[f"pool:{p}"]["T"] = amt
    orig = {u: dict(vs) for u, vs in cap.items()}
    routed = _maxflow(cap, "S", "T") if demand else 0
    alloc = {}
    for st in steps:
        node = f"step{st['step']}"
        for p in st.get("pools", []):
            used = orig[node][f"pool:{p}"] - cap[node][f"pool:{p}"]
            if used:
                alloc.setdefault(st["step"], {})[p] = used
    return {"feasible": routed == demand, "demand": demand, "routed": routed,
            "steps": steps, "allocation": alloc, "unpriced": sorted(unpriced)}
