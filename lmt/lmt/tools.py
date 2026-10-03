"""Diff of two independent encodings, perturbation (renaming/shuffling), and overlays."""
from __future__ import annotations

import copy
import random

from .engine import Engine, Universe, default_universe, search, skeleton

SEM_KEYS = ("kind", "category", "action", "actor", "counterparty", "forms", "assets",
            "foreign", "capacity", "funded_by", "via", "triggers", "on", "when", "then")


def _canon(v):
    if isinstance(v, list):
        return tuple(sorted(_canon(x) for x in v))
    if isinstance(v, dict):
        return tuple(sorted((k, _canon(x)) for k, x in v.items()))
    return v


def semantics(r):
    return tuple((k, _canon(r.get(k))) for k in SEM_KEYS if r.get(k) not in (None, [], {}))


def by_clause(doc):
    out = {}
    for r in doc["rules"]:
        out.setdefault(r["cite"]["clause"], set()).add(semantics(r))
    return out


def structural_diff(a, b):
    """Clauses whose rule semantics differ between two encodings."""
    A, B = by_clause(a), by_clause(b)
    rows = []
    for k in sorted(set(A) | set(B)):
        if A.get(k, set()) != B.get(k, set()):
            rows.append({"clause": k, "only_a": sorted(map(str, A.get(k, set()) - B.get(k, set()))),
                         "only_b": sorted(map(str, B.get(k, set()) - A.get(k, set())))})
    return rows


def first_step_table(doc, universe=None):
    """Which single actions are permitted from 'asset at each entity', and under which clauses."""
    eng = Engine(doc, universe)
    s0 = eng.u.initial()
    table = {}
    for owner in eng.u.entities:
        s = type(s0)(owner, eng.u.entities[owner]["role"] in ("holdings", "borrower", "guarantor"),
                     frozenset(), s0.roles)
        for a in eng.actions(s):
            v = eng.check(a, s)
            if v.ok:
                cl = sorted({_clause_of(doc, rid) for ids in v.used.values() for rid in ids})
                table[a.label()] = cl
            else:
                table[a.label()] = None
    return table


def _clause_of(doc, rid):
    for r in doc["rules"]:
        if r["id"] == rid:
            return r["cite"]["clause"]
    return rid


def perturb(doc, seed=0):
    """Rename every rule id, shuffle rule order. Returns (new doc, id map new->old)."""
    rng = random.Random(seed)
    d = copy.deepcopy(doc)
    ids = [r["id"] for r in d["rules"]]
    new = {old: f"R{rng.randrange(10**8):08d}" for old in ids}
    for r in d["rules"]:
        r["id"] = new[r["id"]]
        if r.get("funded_by"):
            r["funded_by"] = [new.get(x, x) for x in r["funded_by"]]
        if r.get("via") and r["via"].get("except"):
            r["via"]["except"] = [new.get(x, x) for x in r["via"]["except"]]
    rng.shuffle(d["rules"])
    return d, {v: k for k, v in new.items()}


def perturbed_universe(seed=0):
    rng = random.Random(seed)
    base = default_universe()
    names = {e: f"E{rng.randrange(10**6):06d}" for e in base.entities}
    ents = {names[e]: v for e, v in base.entities.items()}
    keys = list(ents)
    rng.shuffle(keys)
    return Universe(entities={k: ents[k] for k in keys}, asset=base.asset, start_owner=names[base.start_owner])


def overlay(doc, extra):
    """Append overlay rules (e.g. a blocker) and synthetic clause text."""
    d = copy.deepcopy(doc)
    d["rules"] = d["rules"] + copy.deepcopy(extra["rules"])
    d.setdefault("synthetic_clauses", {}).update(extra.get("synthetic_clauses", {}))
    return d


def remove(doc, rule_ids):
    d = copy.deepcopy(doc)
    d["rules"] = [r for r in d["rules"] if r["id"] not in set(rule_ids)]
    return d


def path_signature(cert, idmap=None, doc=None):
    """Order-independent summary of all leakage paths: role skeleton + clauses used."""
    sig = set()
    for p in cert["paths"]:
        steps = []
        for st in p:
            used = []
            for cat, ids in sorted(st["used"].items()):
                for rid in ids:
                    rid = idmap.get(rid, rid) if idmap else rid
                    used.append((cat, rid))
            steps.append((st["roles"], st["action"].split(" ")[0], tuple(sorted(used))))
        sig.add(tuple(steps))
    return sig
