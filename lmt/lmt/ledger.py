"""Capacity ledger: can the asset's value pass through the capped baskets a path books?

Flow network for one whole path (exact integers, US dollars):

    S -> step_i                 capacity = value       (each capped investment step carries the full value)
    step_i -> (i, rule)         capacity = value       (a rule node PER STEP: amounts of different steps never mix)
    (i, rule) -> pool           capacity = value       (the pools the rule draws on; pools are shared across steps)
    pool -> T                   capacity = pool amount

Source eligibility (`funded_by`) is enforced on rule nodes, not pools: when a step is booked
under a rule with `funded_by`, the transfer that brought the asset to its current holder (the
inbound transfer, not merely the previous action) may only route through rule nodes listed in
`funded_by`. Pools shared between eligible and ineligible rules do not confer eligibility.

Two models:
- confirmed: a capped rule with no known pool gives no capacity. Used to PROVE feasibility.
- relaxed (optimistic): each such rule gets its own unknown pool, bounded by a finite, justified
  upper bound (value x number of capped steps). Used only to RULE OUT. The independent unknown
  pool is not a model fact: only the AMOUNT is unknown; which rules a step may use and the
  funded_by eligibility are still taken from the rule file, never invented here.

Designations are deemed Investments at the designated entity's fair market value. Universe
assumption: an entity holding the tracked asset is valued at the asset's value; the value of any
other designated entity is unknown (confirmed model: cannot prove; relaxed model: 0).

Status: "feasible" (confirmed model feasible), "indeterminate" (only the relaxed model is
feasible), "infeasible" (even the relaxed model is not).
"""
from __future__ import annotations

from collections import defaultdict


class CapacityConfigError(ValueError):
    """Invalid capacity input: a referenced pool is not declared, or an amount is not an int/null."""


def validate_capacity(pools, rule_pools):
    """pools: {name: int | None}; None = amount unknown (the pool keeps its identity and stays shared).
    Every pool referenced in rule_pools must be declared. Raises CapacityConfigError otherwise."""
    bad = sorted({p for ps in rule_pools.values() for p in ps if p not in pools})
    if bad:
        raise CapacityConfigError(f"pool(s) referenced in rule_pools but not declared in pools: {', '.join(bad)}")
    wrong = sorted(p for p, a in pools.items() if a is not None and (not isinstance(a, int) or isinstance(a, bool) or a < 0))
    if wrong:
        raise CapacityConfigError(f"pool amount must be a non-negative integer or null: {', '.join(wrong)}")


def _maxflow(cap, s, t):
    flow = 0
    while True:
        parent = {s: None}
        q = [s]
        while q and t not in parent:
            u = q.pop(0)
            for v, c in list(cap[u].items()):
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


def inbound_transfer(path, j):
    """Index of the transfer that brought the asset to the holder acting at step j, or None."""
    holder = path[j].get("src")
    for i in range(j - 1, -1, -1):
        st = path[i]
        if st.get("kind", "transfer") == "transfer" and st.get("dst") == holder:
            return i
    return None


def _source_restrictions(path, funded_by):
    """{step index: allowed rule ids} imposed by later funded_by steps; None if inconsistent."""
    allowed = {}
    for j, st in enumerate(path):
        for rid in st.get("designated") or []:
            elig = funded_by.get(rid)
            if not elig:
                continue
            i = inbound_transfer(path, j)
            if i is None:
                return None
            booked = set(path[i].get("designated") or [])
            if not booked or not booked <= set(elig):
                return None
            allowed[i] = allowed.get(i, set(elig)) & set(elig)
    return allowed


def _route(path, value, pools, rule_pools, allowed, relaxed, category):
    cap = defaultdict(lambda: defaultdict(int))
    demand, steps, unpriced, unknown_pools = 0, [], set(), set()
    n_capped = sum(1 for st in path if st["capacity"].get(category) == "capped")
    bound = value * max(n_capped, 1)
    for i, st in enumerate(path):
        if st["capacity"].get(category) != "capped":
            steps.append({"step": i, "needs": 0})
            continue
        need = value
        if st.get("kind") == "designate" and st.get("entity") != st.get("holder"):
            # deemed Investment = fair market value of the designated entity, which the model does not
            # know: confirmed model cannot prove it fits; relaxed model takes the optimistic 0
            if not relaxed:
                return False, {"demand": None, "routed": 0, "steps": steps, "allocation": {},
                               "unpriced": sorted(unpriced), "unknown_pools": sorted(unknown_pools),
                               "unknown_amount_step": i}
            steps.append({"step": i, "needs": 0, "note": "designation of a non-holder: amount unknown"})
            continue
        node = f"step{i}"
        cap["S"][node] = need
        demand += need
        rules = st.get("designated") or st["used"].get(category, [])
        if i in allowed:
            rules = [r for r in rules if r in allowed[i]]
        reach = set()
        for rid in rules:
            rn = f"{node}|{rid}"
            cap[node][rn] = value
            ps = rule_pools.get(rid)
            if ps:
                for p in ps:
                    cap[rn][f"pool:{p}"] = value
                    reach.add(p)
                    if pools.get(p) is None:
                        unknown_pools.add(p)
            else:
                unpriced.add(rid)
                if relaxed:
                    cap[rn][f"pool:unknown:{rid}"] = value
                    cap[f"pool:unknown:{rid}"]["T"] = bound
                    reach.add(f"unknown:{rid}")
        steps.append({"step": i, "needs": value, "rules": sorted(rules), "pools": sorted(reach)})
    for p, amt in pools.items():
        if amt is None:
            # declared pool, amount unknown: 0 in the confirmed model, shared finite bound in the relaxed one
            cap[f"pool:{p}"]["T"] = bound if relaxed else 0
        else:
            cap[f"pool:{p}"]["T"] = amt
    orig = {u: dict(vs) for u, vs in cap.items()}
    routed = _maxflow(cap, "S", "T") if demand else 0
    alloc = {}
    for st in steps:
        for rid in st.get("rules", []):
            rn = f"step{st['step']}|{rid}"
            for pn, c0 in orig.get(rn, {}).items():
                used = c0 - cap[rn][pn]
                if used:
                    alloc.setdefault(st["step"], {})[pn.split("pool:", 1)[1]] = used
    return routed == demand, {"demand": demand, "routed": routed, "steps": steps,
                              "allocation": alloc, "unpriced": sorted(unpriced),
                              "unknown_pools": sorted(unknown_pools)}


def check_path(path, value, pools, rule_pools, funded_by=None, category="investments"):
    """Three-state capacity check for one path. `feasible` is True only in the confirmed model."""
    allowed = _source_restrictions(path, funded_by or {})
    if allowed is None:
        return {"feasible": False, "status": "infeasible", "reason": "funded_by source not satisfied",
                "demand": 0, "routed": 0, "steps": [], "allocation": {}, "unpriced": [], "unknown_pools": []}
    unknown_conds = [f"condition {c['rule']}: {c['text']} [{c['type']}/unknown]"
                     for st in path for c in st.get("conditions", []) if c["status"] == "unknown"]
    ok, info = _route(path, value, pools, rule_pools, allowed, relaxed=False, category=category)
    if ok and not unknown_conds:
        return {"feasible": True, "status": "feasible", **info}
    if ok:
        # capacity fits, but a relied-on condition has unknown status: never a candidate
        return {"feasible": False, "status": "indeterminate", **info, "relaxed_allocation": info["allocation"],
                "unknowns": unknown_conds}
    ok_r, info_r = _route(path, value, pools, rule_pools, allowed, relaxed=True, category=category)
    status = "indeterminate" if ok_r else "infeasible"
    return {"feasible": False, "status": status, **info,
            "relaxed_allocation": info_r["allocation"] if ok_r else {},
            "unknowns": [f"rule {r}: no pool mapping, amount unknown" for r in info["unpriced"]]
                        + [f"pool {p}: amount unknown" for p in info.get("unknown_pools", [])]
                        + unknown_conds}


def funded_by_map(doc):
    return {r["id"]: list(r["funded_by"]) for r in doc["rules"] if r.get("funded_by")}
