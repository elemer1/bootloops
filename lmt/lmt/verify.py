"""Independent checker. Imports nothing from engine.py or ledger.py.

It re-implements the rule semantics from rules/SCHEMA.md with different algorithms
(depth-first enumeration of every action sequence without state pruning, and Hall's
condition over step subsets instead of max-flow) and recomputes, for each
interpretation profile and asset value, whether a capacity-feasible leakage path exists
and which (shape, booking) signatures achieve it. Agreement with the engine is the
acceptance test; disagreement means a bug in one of them.

Shared assumption with the engine: both read the same rule file and the same schema.
This catches search and bookkeeping bugs, not encoding errors.
"""
from __future__ import annotations

import itertools
import re

import yaml

LP = {"holdings", "borrower", "guarantor"}
RS = {"guarantor", "nlp_rs"}


def _on(r):
    return r.get("on", r.get(True))


def _match(pat, val):
    return (not pat) or ("any" in pat) or (val in pat)


class Checker:
    def __init__(self, doc, scenario, assumptions):
        self.rules = [r for r in doc["rules"] if not r.get("assumption") or r["assumption"] in assumptions]
        self.id = {r["id"]: r for r in self.rules}
        self.facts = [f for f in scenario.get("facts", []) if not f["holds"]]
        self.overrides = list(scenario.get("condition_status") or [])
        self.ents = {"H": ("holdings", False), "B": ("borrower", False), "G": ("guarantor", False),
                     "Nd": ("nlp_rs", False), "Nf": ("nlp_rs", True), "U": ("unrestricted", False)}

    PARENT = {"B": "H", "G": "B", "Nd": "B", "Nf": "B", "U": "B"}

    # ---- condition status, re-implemented (see SCHEMA.md for the order of resolution)
    ORDER = ["proven", "assumed", "unknown", "refuted"]

    def cond_state(self, c):
        text = c if isinstance(c, str) else c["text"]
        for o in self.overrides:
            if re.search(o["pattern"], text, re.I):
                return o["status"]
        for f in self.facts:
            if re.search(f["pattern"], text, re.I):
                return "refuted"
        return "assumed" if isinstance(c, str) else c.get("status", "assumed")

    def own_state(self, r):
        memo = self.__dict__.setdefault("_own", {})
        if r["id"] not in memo:
            states = [self.cond_state(c) for c in r.get("conditions") or []]
            memo[r["id"]] = max(states, key=self.ORDER.index) if states else "proven"
        return memo[r["id"]]

    def dead(self, r):
        return self.own_state(r) == "refuted"

    def rule_state(self, rid, ctx, held_via, depth=0):
        """Own conditions, plus (for a cross-reference) the best-supported rule pointed to."""
        r = self.id[rid]
        s = self.own_state(r)
        v = r.get("via")
        if v and depth < 4:
            inner = self.allowed(v["category"], ctx, held_via, set(v.get("except", [])) | {rid})
            if inner:
                best = min((self.rule_state(i, ctx, held_via, depth + 1) for i in inner), key=self.ORDER.index)
                s = max([s, best], key=self.ORDER.index)
        return s

    def fits(self, r, kind, actor, cp, foreign, form, asset="ip"):
        if r.get("action", "transfer") != kind:
            return False
        if not (_match(r.get("actor"), actor) and _match(r.get("counterparty"), cp)):
            return False
        if r.get("foreign", "any") != "any" and bool(r["foreign"]) != foreign:
            return False
        if kind == "transfer" and not (_match(r.get("assets"), asset) and _match(r.get("forms"), form)):
            return False
        return True

    def allowed(self, cat, ctx, held_via, skip, depth=0):
        if depth > 4:
            return []
        out = []
        for r in self.rules:
            if r["kind"] != "exception" or r.get("category") != cat or r["id"] in skip or self.dead(r):
                continue
            if not self.fits(r, *ctx):
                continue
            # whole-asset model: everything that arrived must have arrived under an eligible basket
            if r.get("funded_by") and not (ctx[0] == "transfer" and held_via and held_via <= set(r["funded_by"])):
                continue
            v = r.get("via")
            if v and not self.allowed(v["category"], ctx, held_via, set(skip) | set(v.get("except", [])) | {r["id"]}, depth + 1):
                continue
            out.append(r["id"])
        return out

    def uncapped(self, rid, ctx, held_via, depth=0):
        r = self.id[rid]
        if r.get("via"):
            v = r["via"]
            inner = self.allowed(v["category"], ctx, held_via, set(v.get("except", [])) | {rid})
            return depth < 4 and any(self.uncapped(i, ctx, held_via, depth + 1) for i in inner)
        return r.get("capacity") == "unlimited"

    def step(self, state, act):
        """Return list of (new_state, record) for each booking, or [] if not permitted."""
        owner, enc, held_via, roles = state
        if act[0] == "transfer":
            _, src, dst, form = act
            ctx = ("transfer", roles[src], roles[dst], self.ents[dst][1], form)
        else:
            _, ent = act
            ctx = ("designate", "borrower", roles[ent], self.ents[ent][1], "")
        cats = set()
        for r in self.rules:
            if r["kind"] == "characterization" and r.get("action", "transfer") == ctx[0]:
                if ctx[0] == "designate" or _match(r.get("forms"), ctx[4]):
                    cats |= set(r["triggers"])
        if not cats:
            return []
        for r in self.rules:
            if r["kind"] == "prohibition" and self.fits(r, *ctx):
                if r.get("owns_tracked_asset") and not (act[0] == "designate" and act[1] == owner):
                    continue
                return []
        used = {}
        for c in cats:
            ids = self.allowed(c, ctx, held_via, set())
            if not ids:
                return []
            used[c] = ids
        # lien effects
        new_roles = dict(roles)
        new_owner = owner
        if act[0] == "transfer":
            new_owner = act[2]
        else:
            new_roles[act[1]] = "unrestricted"
        new_enc = enc
        for r in self.rules:
            if r["kind"] != "effect" or _on(r) != act[0]:
                continue
            target = act[2] if act[0] == "transfer" else act[1]
            if not _match((r.get("when") or {}).get("counterparty"), new_roles[target]):
                continue
            if act[0] == "designate" and act[1] != owner:
                continue
            if r["then"] == "release_lien":
                new_enc = False
            elif r["then"] == "attach_lien":
                new_enc = True
        if new_roles[new_owner] in LP:
            new_enc = True
        inv = used.get("investments")
        if not inv:
            bookings = [(None, frozenset())]
        else:
            # same booking rule for transfers and (deemed-Investment) designations: a non-empty set of
            # capped baskets sharing the value, or one uncapped basket
            cap = [i for i in inv if not self.uncapped(i, ctx, held_via)]
            unc = [i for i in inv if i not in cap]
            bookings = [("cap", frozenset(c)) for n in range(1, len(cap) + 1) for c in itertools.combinations(cap, n)]
            bookings += [("unc", frozenset([i])) for i in unc]
        # condition status the step relies on: every booked basket, plus the best rule per other category
        other = [min((self.rule_state(i, ctx, held_via) for i in ids), key=self.ORDER.index)
                 for c, ids in used.items() if c != "investments"]
        out = []
        for kind, b in bookings:
            st = other + [self.rule_state(i, ctx, held_via) for i in b]
            cond = max(st, key=self.ORDER.index) if st else "proven"
            nv = b if act[0] == "transfer" else held_via
            out.append(((new_owner, new_enc, nv, new_roles), {"act": act, "booking": sorted(b), "capped": kind == "cap",
                                                              "holder": owner, "cond": cond}))
        return out

    def acts(self, state):
        owner, _, _, roles = state
        for dst in self.ents:
            if dst == owner:
                continue
            for form in ("contribution", "dividend", "sale"):
                if form == "dividend" and self.PARENT.get(owner) != dst:
                    continue          # dividends only to the payer's parent (H -> B -> {G, Nd, Nf, U})
                yield ("transfer", owner, dst, form)
        for e in self.ents:
            if roles[e] in RS:
                yield ("designate", e)

    def paths(self, depth):
        s0 = ("G", True, frozenset(), {e: v[0] for e, v in self.ents.items()})
        out = []

        def dfs(s, trail):
            owner, enc, _, roles = s
            if trail and roles[owner] == "unrestricted" and not enc:
                # leakage = no step returned fair-market-value consideration (no `sale` step)
                if not any(st["act"][0] == "transfer" and st["act"][3] == "sale" for st in trail):
                    out.append(trail)
                return
            if len(trail) == depth:
                return
            for a in self.acts(s):
                for s2, rec in self.step(s, a):
                    rec["roles"] = f"{s[3][a[1]]}->{s2[3][s2[0]]}"
                    dfs(s2, trail + [rec])
        dfs(s0, [])
        return out


def _incoming(path, j):
    """Position of the transfer whose recipient is the entity acting at step j (independent of ledger.py)."""
    act = path[j]["act"]
    actor = act[1] if act[0] == "transfer" else None
    k = j - 1
    while k >= 0:
        a = path[k]["act"]
        if a[0] == "transfer" and a[2] == actor:
            return k
        k -= 1
    return None


def hall_status(path, value, pools, rule_pools, funded_by):
    """'feasible' / 'indeterminate' / 'infeasible' by Hall's condition over capped steps.

    Source eligibility: for each step booked under a rule with funded_by, the inbound transfer's
    booking must be a non-empty subset of the eligible rules (then only those rules' pools can
    carry it). Confirmed model: unpriced capped rules give nothing. Relaxed model: each unpriced
    rule gets its own pool of size value x (number of capped steps)."""
    for j, st in enumerate(path):
        for rid in st["booking"]:
            elig = funded_by.get(rid)
            if elig:
                k = _incoming(path, j)
                if k is None or not path[k]["booking"] or not set(path[k]["booking"]) <= set(elig):
                    return "infeasible"
    capped = [st for st in path if st["capped"]]
    bound = value * max(len(capped), 1)
    foreign_designation = [st for st in capped if st["act"][0] == "designate" and st["act"][1] != st["holder"]]

    def ok(relaxed):
        if foreign_designation and not relaxed:
            return False          # deemed-Investment amount of a non-holder is unknown
        neigh = []
        # declared-but-unknown amounts (None): 0 when proving, shared finite bound when relaxing
        sizes = {p: (a if a is not None else (bound if relaxed else 0)) for p, a in pools.items()}
        for st in capped:
            if st in foreign_designation:
                continue          # relaxed model: optimistic amount 0
            ps = set()
            for rid in st["booking"]:
                if rid in rule_pools:
                    ps |= set(rule_pools[rid])
                elif relaxed:
                    ps.add("?" + rid)
                    sizes["?" + rid] = bound
            neigh.append(ps)
        for n in range(1, len(neigh) + 1):
            for X in itertools.combinations(neigh, n):
                reach = set().union(*X)
                if value * n > sum(sizes.get(p, 0) for p in reach):
                    return False
        return True

    unknown = any(st.get("cond") == "unknown" for st in path)
    if ok(False):
        return "indeterminate" if unknown else "feasible"
    return "indeterminate" if ok(True) else "infeasible"


def aa_threshold(path, value, pools, rule_pools, funded_by, aa):
    """Least AA (x_c confirmed, x_r relaxed) by Hall's condition, computed in closed form:
    for every set X of capped steps, value*|X| <= capacity(N(X)); if the AA pool is in N(X) the
    deficit value*|X| - capacity(N(X) without AA) is a lower bound on AA, else a positive deficit
    means no AA suffices. Threshold = max(0, all such deficits). Returns (x_c, x_r), None = no AA."""
    for j, st in enumerate(path):
        for rid in st["booking"]:
            elig = funded_by.get(rid)
            if elig:
                k = _incoming(path, j)
                if k is None or not path[k]["booking"] or not set(path[k]["booking"]) <= set(elig):
                    return None, None
    capped = [st for st in path if st["capped"]]
    bound = value * max(len(capped), 1)
    foreign = [st for st in capped if st["act"][0] == "designate" and st["act"][1] != st["holder"]]
    unknown_cond = any(st.get("cond") == "unknown" for st in path)

    def least(relaxed):
        if not relaxed and (foreign or unknown_cond):
            return None
        sizes = {p: (a if a is not None else (bound if relaxed else 0)) for p, a in pools.items() if p != aa}
        neigh = []
        for st in capped:
            if st in foreign:
                continue
            ps = set()
            for rid in st["booking"]:
                if rid in rule_pools:
                    ps |= set(rule_pools[rid])
                elif relaxed:
                    ps.add("?" + rid)
                    sizes["?" + rid] = bound
            neigh.append(ps)
        need = 0
        for n in range(1, len(neigh) + 1):
            for X in itertools.combinations(neigh, n):
                reach = set().union(*X)
                deficit = value * n - sum(sizes.get(p, 0) for p in reach if p != aa)
                if deficit > 0:
                    if aa not in reach:
                        return None
                    need = max(need, deficit)
        return need

    return least(False), least(True)


def hall_feasible(path, value, pools, rule_pools, funded_by=None):
    return hall_status(path, value, pools, rule_pools, funded_by or {}) == "feasible"


def signature(path):
    """Entity-level: the full action (who, to whom, which form / which entity) plus the booking.
    Role-level shapes are for reports only; they would merge G->Nd->U with G->Nf->U."""
    out = []
    for st in path:
        a = st["act"]
        act = f"designate {a[1]}" if a[0] == "designate" else f"transfer[{a[3]}] {a[1]}->{a[2]}"
        out.append((act, tuple(sorted(st["booking"]))))
    return tuple(out)


def _check_pools(pools, rule_pools):
    for rid, ps in rule_pools.items():
        for p in ps:
            if p not in pools:
                raise ValueError(f"verify: rule {rid} draws on undeclared pool {p}")
    for p, a in pools.items():
        if a is not None and not (type(a) is int and a >= 0):
            raise ValueError(f"verify: pool {p} amount must be a non-negative integer or null")


def check(rules_doc, scenario_path, depth=3):
    """{(profile, value name): {"feasible": signatures, "indeterminate": signatures}}"""
    sc = yaml.safe_load(open(scenario_path))
    cap = sc["capacity"]
    _check_pools(cap["pools"], cap["rule_pools"])
    aa = sc.get("aa_parameter")
    ids = sorted((rules_doc.get("assumptions") or {}).keys())
    fb = {r["id"]: list(r["funded_by"]) for r in rules_doc["rules"] if r.get("funded_by")}
    res = {}
    for n in range(len(ids) + 1):
        for prof in itertools.combinations(ids, n):
            ps = Checker(rules_doc, sc, set(prof)).paths(depth)
            for vname, value in cap["values"].items():
                out = {"feasible": set(), "indeterminate": set(), "thresholds": {}}
                for p in ps:
                    s = hall_status(p, value, cap["pools"], cap["rule_pools"], fb)
                    if s in out:
                        out[s].add(signature(p))
                    if aa:
                        out["thresholds"][signature(p)] = aa_threshold(p, value, cap["pools"], cap["rule_pools"], fb, aa)
                res[(prof, vname)] = out
    return res
