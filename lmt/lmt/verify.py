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
        self.ents = {"H": ("holdings", False), "B": ("borrower", False), "G": ("guarantor", False),
                     "Nd": ("nlp_rs", False), "Nf": ("nlp_rs", True), "U": ("unrestricted", False)}

    def dead(self, r):
        return any(re.search(f["pattern"], c, re.I) for c in r.get("conditions") or [] for f in self.facts)

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
            if r.get("funded_by") and not (ctx[0] == "transfer" and set(r["funded_by"]) & held_via):
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
        if not inv or act[0] != "transfer":
            bookings = [(None, frozenset())] if not inv else \
                [(("cap" if not self.uncapped(i, ctx, held_via) else "unc"), frozenset([i])) for i in inv]
        else:
            cap = [i for i in inv if not self.uncapped(i, ctx, held_via)]
            unc = [i for i in inv if i not in cap]
            bookings = [("cap", frozenset(c)) for n in range(1, len(cap) + 1) for c in itertools.combinations(cap, n)]
            bookings += [("unc", frozenset([i])) for i in unc]
        out = []
        for kind, b in bookings:
            nv = b if act[0] == "transfer" else held_via
            out.append(((new_owner, new_enc, nv, new_roles), {"act": act, "booking": sorted(b), "capped": kind == "cap"}))
        return out

    def acts(self, state):
        owner, _, _, roles = state
        for dst in self.ents:
            if dst == owner:
                continue
            for form in ("contribution", "dividend", "sale"):
                if form == "dividend" and roles[dst] == "unrestricted":
                    continue
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


def hall_feasible(path, value, pools, rule_pools):
    """Feasible iff for every subset X of capped steps, value*|X| <= capacity of pools reachable from X."""
    capped = [set(p for rid in st["booking"] for p in rule_pools.get(rid, [])) for st in path if st["capped"]]
    for n in range(1, len(capped) + 1):
        for X in itertools.combinations(capped, n):
            reach = set().union(*X)
            if value * n > sum(pools[p] for p in reach):
                return False
    return True


def signature(path):
    return tuple((st["roles"], st["act"][0] if st["act"][0] == "designate" else f"transfer[{st['act'][3]}]",
                  tuple(st["booking"])) for st in path)


def check(rules_doc, scenario_path, depth=3):
    sc = yaml.safe_load(open(scenario_path))
    cap = sc["capacity"]
    ids = sorted((rules_doc.get("assumptions") or {}).keys())
    res = {}
    for n in range(len(ids) + 1):
        for prof in itertools.combinations(ids, n):
            ps = Checker(rules_doc, sc, set(prof)).paths(depth)
            for vname, value in cap["values"].items():
                feas = {signature(p) for p in ps if hall_feasible(p, value, cap["pools"], cap["rule_pools"])}
                res[(prof, vname)] = feas
    return res
