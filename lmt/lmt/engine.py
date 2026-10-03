"""Deterministic reachability search over encoded covenant rules.

No LLM is involved here: the engine reads a rule file (see rules/SCHEMA.md) and an
entity universe, and enumerates every action sequence up to a depth bound.

State: who owns the tracked asset, whether the lenders' lien is on it, which
investment rules carried it to its current owner (for `funded_by` conditions), and
the role of every entity (designations change roles).
"""
from __future__ import annotations

import itertools
import json
from collections import deque
from dataclasses import dataclass, field

import yaml

from .conditions import RANK, Resolver, worst

ROLES = ("holdings", "borrower", "guarantor", "nlp_rs", "unrestricted")
LOAN_PARTY = {"holdings", "borrower", "guarantor"}
RESTRICTED_SUB = {"guarantor", "nlp_rs"}
FORMS = ("contribution", "dividend", "sale", "license")
CATEGORIES = ("investments", "dispositions", "restricted_payments", "liens", "designation")
KINDS = ("characterization", "exception", "prohibition", "effect", "na")


class RuleError(ValueError):
    pass


# --------------------------------------------------------------------------- rules

def load_rules(path):
    with open(path) as f:
        doc = yaml.safe_load(f)
    return validate(doc)


def validate(doc):
    if not isinstance(doc, dict) or "rules" not in doc or "agreement" not in doc:
        raise RuleError("rule file needs top-level 'agreement' and 'rules'")
    seen = set()
    for r in doc["rules"]:
        if True in r:  # YAML 1.1 reads a bare `on:` key as boolean True
            r["on"] = r.pop(True)
        rid = r.get("id")
        if not rid or rid in seen:
            raise RuleError(f"missing or duplicate rule id: {rid!r}")
        seen.add(rid)
        if r.get("kind") not in KINDS:
            raise RuleError(f"{rid}: unknown kind {r.get('kind')!r}")
        c = r.get("cite") or {}
        if not c.get("clause") or not c.get("quote"):
            raise RuleError(f"{rid}: every rule needs cite.clause and cite.quote")
        if r["kind"] in ("exception",) and r.get("category") not in CATEGORIES:
            raise RuleError(f"{rid}: bad category {r.get('category')!r}")
        for key in ("actor", "counterparty"):
            for role in r.get(key) or []:
                if role != "any" and role not in ROLES:
                    raise RuleError(f"{rid}: unknown role {role!r} in {key}")
        for form in r.get("forms") or []:
            if form not in FORMS:
                raise RuleError(f"{rid}: unknown form {form!r}")
        for cat in r.get("triggers") or []:
            if cat not in CATEGORIES:
                raise RuleError(f"{rid}: unknown category {cat!r} in triggers")
    return doc


def _roles_match(pattern, role):
    return not pattern or "any" in pattern or role in pattern


def _list_match(pattern, value):
    return not pattern or "any" in pattern or value in pattern


# --------------------------------------------------------------------------- world

@dataclass(frozen=True)
class State:
    owner: str                      # entity id holding the tracked asset
    encumbered: bool
    arrived_via: frozenset          # investment-rule ids that permitted the last inbound transfer
    roles: tuple                    # ((entity id, role), ...) sorted

    def role(self, eid):
        return dict(self.roles)[eid]


@dataclass
class Universe:
    entities: dict                  # id -> {"role": ..., "foreign": bool}
    asset: str = "ip"
    start_owner: str = "G"
    facts: list = field(default_factory=list)   # [{"pattern": regex, "holds": bool, "why": str}]
    condition_status: list = field(default_factory=list)  # [{"pattern", "status", "why", "source"}]

    def condition_fails(self, cond):
        """A rule condition is known false in this scenario if a fact with holds=False matches it."""
        import re
        for f in self.facts:
            if not f["holds"] and re.search(f["pattern"], cond, re.I):
                return f
        return None

    def initial(self):
        roles = tuple(sorted((e, v["role"]) for e, v in self.entities.items()))
        enc = self.entities[self.start_owner]["role"] in LOAN_PARTY
        return State(self.start_owner, enc, frozenset(), roles)


def default_universe():
    """One entity of every role the vocabulary allows. A modeling assumption, stated
    in every certificate: the borrower group has (or can form) such entities."""
    return Universe(entities={
        "H": {"role": "holdings", "foreign": False, "parent": None},
        "B": {"role": "borrower", "foreign": False, "parent": "H"},
        "G": {"role": "guarantor", "foreign": False, "parent": "B"},
        "Nd": {"role": "nlp_rs", "foreign": False, "parent": "B"},
        "Nf": {"role": "nlp_rs", "foreign": True, "parent": "B"},
        "U": {"role": "unrestricted", "foreign": False, "parent": "B"},
    })   # ownership tree: H -> B -> {G, Nd, Nf, U}; dividends run only to the payer's parent


@dataclass(frozen=True)
class Action:
    kind: str                       # transfer | designate
    src: str = ""
    dst: str = ""
    form: str = ""
    entity: str = ""

    def label(self):
        if self.kind == "transfer":
            return f"transfer[{self.form}] {self.src}->{self.dst}"
        return f"designate {self.entity}"


@dataclass
class Verdict:
    ok: bool
    used: dict = field(default_factory=dict)        # category -> [rule ids]
    denied: list = field(default_factory=list)      # reasons
    assumptions: list = field(default_factory=list)
    capacity: dict = field(default_factory=dict)    # category -> capped | uncapped
    designated: list = field(default_factory=list)  # investments basket(s) the step is booked under
    rule_dep: dict = field(default_factory=dict)    # rule id -> (effective status, [conditions])
    cat_dep: dict = field(default_factory=dict)     # non-investment category -> (status, [conditions], rule id)
    cond_status: str = "proven"                     # worst condition status the step relies on
    conditions: list = field(default_factory=list)  # conditions the step relies on (resolved)


class Engine:
    def __init__(self, doc, universe=None, assumptions=None):
        """assumptions: set of interpretation-assumption ids treated as true (None = all of them).
        A rule tagged `assumption: Ak` is active only when Ak is in the set."""
        self.doc = doc
        declared = set((doc.get("assumptions") or {}).keys())
        self.assumptions = declared if assumptions is None else set(assumptions)
        self.rules = [r for r in doc["rules"] if not r.get("assumption") or r["assumption"] in self.assumptions]
        self.u = universe or default_universe()
        self.resolver = Resolver(self.u.condition_status, self.u.facts)
        self.by_id = {r["id"]: r for r in self.rules}
        self._status_memo = {}
        self._eff_memo = {}
        self.by_kind = {k: [r for r in self.rules if r["kind"] == k] for k in KINDS}

    @staticmethod
    def u_condition_status(universe):
        return (universe.condition_status if universe else []) or []

    # ---- action enumeration
    def actions(self, s: State):
        ents = [e for e, _ in s.roles]
        for dst in ents:
            if dst != s.owner:
                for form in FORMS:
                    if form == "license":
                        continue  # licenses move use rights, not title; not tracked in Phase 0
                    if form == "dividend" and self.u.entities[s.owner].get("parent") != dst:
                        continue  # a dividend runs only to the payer's parent in the ownership tree
                    yield Action("transfer", src=s.owner, dst=dst, form=form)
        for e in ents:
            if s.role(e) in RESTRICTED_SUB:
                yield Action("designate", entity=e)

    # ---- matching helpers
    def _parties(self, a: Action, s: State):
        if a.kind == "transfer":
            return s.role(a.src), s.role(a.dst), self.u.entities[a.dst].get("foreign", False)
        return "borrower", s.role(a.entity), self.u.entities[a.entity].get("foreign", False)

    def _matches(self, r, a: Action, s: State):
        if r.get("action", "transfer") != a.kind:
            return False
        actor, cp, foreign = self._parties(a, s)
        if not _roles_match(r.get("actor"), actor):
            return False
        if not _roles_match(r.get("counterparty"), cp):
            return False
        fr = r.get("foreign", "any")
        if fr != "any" and bool(fr) != bool(foreign):
            return False
        if a.kind == "transfer":
            if not _list_match(r.get("assets"), self.u.asset):
                return False
            if not _list_match(r.get("forms"), a.form):
                return False
        return True

    def categories(self, a: Action, s: State):
        cats, why = set(), []
        for r in self.by_kind["characterization"]:
            if r.get("action", "transfer") != a.kind:
                continue
            if a.kind == "transfer" and not _list_match(r.get("forms"), a.form):
                continue
            cats.update(r["triggers"])
            why.append(r["id"])
        return sorted(cats), why

    def permitted_in(self, cat, a: Action, s: State, excluded=frozenset(), depth=0):
        """Rule ids under which `a` is permitted in category `cat` (empty = not permitted)."""
        if depth > 4:
            return []
        hits = []
        for r in self.by_kind["exception"]:
            if r["category"] != cat or r["id"] in excluded or not self._matches(r, a, s):
                continue
            if self.rule_status(r["id"])[0] == "refuted":
                continue
            fb = r.get("funded_by")
            # Whole-asset model: the onward transfer carries the full value, so ALL of it must have
            # arrived under an eligible basket. The inbound booking must be a non-empty SUBSET of
            # funded_by (a label overlap would let $1 of eligible funding unlock $100 onward).
            # Partial transfers, mixed-source splitting and source reallocation are not supported.
            if fb and not (a.kind == "transfer" and s.arrived_via and s.arrived_via <= set(fb)):
                continue
            via = r.get("via")
            if via:
                inner = self.permitted_in(via["category"], a, s,
                                          excluded | set(via.get("except", [])) | {r["id"]}, depth + 1)
                if not inner:
                    continue
            hits.append(r["id"])
        return hits

    def capacity_of(self, cat, ids, a, s, depth=0):
        """'uncapped' if some permitting rule is unlimited; a cross-reference (`via`) rule inherits the
        capacity of the rules it points to."""
        ex = self.by_id
        for rid in ids:
            r = ex[rid]
            via = r.get("via")
            if via:
                if depth < 4:
                    inner = self.permitted_in(via["category"], a, s, frozenset(via.get("except", [])) | {rid})
                    if inner and self.capacity_of(via["category"], inner, a, s, depth + 1) == "uncapped":
                        return "uncapped"
            elif r.get("capacity") == "unlimited":
                return "uncapped"
        return "capped"

    def check(self, a: Action, s: State) -> Verdict:
        cats, chars = self.categories(a, s)
        v = Verdict(ok=True)
        if not cats:
            v.ok = False
            v.denied.append("no characterization rule covers this action (unmodeled, treated as not permitted)")
            return v
        for r in self.by_kind["prohibition"]:
            if r.get("owns_tracked_asset") and not (a.kind == "designate" and a.entity == s.owner):
                continue
            if self._matches(r, a, s):
                v.ok = False
                v.denied.append(f"prohibited by {r['id']}")
        for cat in cats:
            hits = self.permitted_in(cat, a, s)
            if hits:
                v.used[cat] = hits
            else:
                v.ok = False
                v.denied.append(f"no exception in {cat}")
        if v.ok:
            v.capacity = {cat: self.capacity_of(cat, ids, a, s) for cat, ids in v.used.items()}
            for cat, ids in v.used.items():
                for rid in ids:
                    v.rule_dep[rid] = self.effective(rid, a, s)
                if cat != "investments":
                    best = min(ids, key=lambda r: (RANK[v.rule_dep[r][0]], len(v.rule_dep[r][1]), r))
                    v.cat_dep[cat] = (v.rule_dep[best][0], v.rule_dep[best][1], best)
        return v

    def rule_status(self, rid):
        if rid not in self._status_memo:
            self._status_memo[rid] = self.resolver.rule_status(self.by_id[rid])
        return self._status_memo[rid]

    def effective(self, rid, a, s, depth=0):
        """(status, conditions) a rule relies on: its own conditions, and for a cross-reference the
        best-supported rule it points to."""
        key = (rid, a, s, depth)
        if key not in self._eff_memo:
            self._eff_memo[key] = self._effective(rid, a, s, depth)
        return self._eff_memo[key]

    def _effective(self, rid, a, s, depth):
        ex = self.by_id
        st, cs = self.rule_status(rid)
        cs = [{**c, "rule": rid} for c in cs]
        via = ex[rid].get("via")
        if via and depth < 4:
            inner = self.permitted_in(via["category"], a, s, frozenset(via.get("except", [])) | {rid})
            if inner:
                deps = [self.effective(i, a, s, depth + 1) for i in inner]
                b = min(deps, key=lambda d: (RANK[d[0]], len(d[1])))
                st, cs = worst([st, b[0]]), cs + b[1]
        return st, cs

    def designations(self, a: Action, s: State, v: Verdict):
        """How the step can be booked under the investments covenant.

        Either (i) a non-empty set of capped baskets, across which the ledger splits the value
        (e.g. part under 7.02(c)(iv), part under 7.02(n)); or (ii) a single uncapped basket.
        The booking decides capacity consumption and which later `funded_by` conditions the
        received property can satisfy. Mixed bookings are not generated: they only ever give
        partial funding credit, so they never open a path that (i) or (ii) does not."""
        import copy
        import itertools
        ids = v.used.get("investments")
        if not ids:
            self._set_conditions(v, booked=[])
            return [v]
        capped = [r for r in ids if self.capacity_of("investments", [r], a, s) == "capped"]
        uncapped = [r for r in ids if r not in capped]
        bookings = [frozenset(c) for n in range(1, len(capped) + 1) for c in itertools.combinations(capped, n)]
        bookings += [frozenset([r]) for r in uncapped]
        out = []
        for b in bookings:
            vd = copy.copy(v)
            vd.designated = sorted(b)
            vd.capacity = dict(v.capacity)
            vd.capacity["investments"] = "capped" if b <= set(capped) else "uncapped"
            self._set_conditions(vd, booked=sorted(b))
            out.append(vd)
        return out

    def _set_conditions(self, v, booked):
        """Every booked basket must hold (the value is split across them); for other categories the
        best-supported permitting rule is relied on."""
        sts, cs = [], []
        for rid in booked:
            st, c = v.rule_dep[rid]
            sts.append(st)
            cs += c
        for cat, (st, c, _) in v.cat_dep.items():
            sts.append(st)
            cs += c
        v.cond_status = worst(sts)
        seen, uniq = set(), []
        for c in cs:
            k = (c["rule"], c["text"])
            if k not in seen:
                seen.add(k)
                uniq.append(c)
        v.conditions = uniq
        v.assumptions = [f"{c['rule']}: {c['text']} [{c['type']}/{c['status']}]" for c in uniq if c["status"] != "proven"]

    def apply(self, a: Action, s: State, v: Verdict) -> tuple[State, list]:
        roles = dict(s.roles)
        owner, enc, via = s.owner, s.encumbered, frozenset()
        if a.kind == "transfer":
            owner = a.dst
            via = frozenset(v.designated) if v.designated else frozenset()
        else:
            roles[a.entity] = "unrestricted"
            via = s.arrived_via
        fired = []
        for r in self.by_kind["effect"]:
            if r.get("on") != a.kind:
                continue
            w = r.get("when") or {}
            cp_role = roles[a.dst] if a.kind == "transfer" else roles[a.entity]
            if not _roles_match(w.get("counterparty"), cp_role):
                continue
            if a.kind == "designate" and a.entity != owner:
                continue  # designating some other entity does not touch the tracked asset
            if r["then"] == "release_lien" and s.encumbered:
                enc = False
                fired.append(r["id"])  # every release ground that applies, not only the first
            elif r["then"] == "attach_lien" and not enc:
                enc = True
                fired.append(r["id"])
        if roles[owner] in LOAN_PARTY and not enc:
            enc = True  # a Loan Party's assets are collateral; re-attach
            fired.append("(loan-party asset is collateral)")
        return State(owner, enc, via, tuple(sorted(roles.items()))), fired


def goal_leak(s: State):
    """Tracked asset owned by an Unrestricted Subsidiary, free of the lenders' lien."""
    return s.role(s.owner) == "unrestricted" and not s.encumbered


def search(engine: Engine, depth=4, goal=goal_leak, no_sale=True):
    """Reference enumeration: EVERY action sequence up to `depth`.

    No cross-path deduplication and no removal of repeated states within a path: capacity use
    is not part of the state, so two paths reaching the same structural state are not
    interchangeable. Termination comes from the depth bound alone. The only early stop: a path
    is not extended once it reaches the goal (verify.py applies the same rule).

    no_sale: a path using a `sale` step moves value for fair consideration, so it is reported
    separately and does not count as leakage."""
    s0 = engine.u.initial()
    paths, sale_paths = [], []
    denials = {}
    expanded = 0
    frontier = deque([(s0, [])])
    while frontier:
        s, path = frontier.popleft()
        if goal(s) and path:
            (sale_paths if any(st["action"].startswith("transfer[sale]") for st in path) else paths).append(path)
            continue
        if len(path) >= depth:
            continue
        expanded += 1
        for a in engine.actions(s):
            v = engine.check(a, s)
            if not v.ok:
                denials.setdefault(a.label(), set()).update(v.denied)
                continue
            for vd in engine.designations(a, s, v):
                s2, fired = engine.apply(a, s, vd)
                step = {"action": a.label(), "kind": a.kind, "src": a.src or "", "dst": a.dst or "",
                        "entity": a.entity or "", "holder": s.owner,
                        "roles": f"{s.role(a.src or a.entity)}->{s2.role(s2.owner)}",
                        "used": vd.used, "designated": vd.designated, "capacity": vd.capacity,
                        "cond_status": vd.cond_status, "conditions": vd.conditions,
                        "effects": fired, "assumptions": vd.assumptions}
                frontier.append((s2, path + [step]))
    return {
        "agreement": engine.doc["agreement"],
        "assumptions_on": sorted(engine.assumptions),
        "bound": {"depth": depth, "entities": engine.u.entities, "asset": engine.u.asset,
                  "start_owner": engine.u.start_owner, "mode": "reference (no pruning)"},
        "reachable": bool(paths),
        "paths": paths,
        "sale_paths": sale_paths,
        "states_expanded": expanded,
        "denials": {k: sorted(v) for k, v in sorted(denials.items())},
    }


def skeleton(path):
    """Role-level shape of a path, e.g. ['guarantor->nlp_rs', 'nlp_rs->unrestricted']."""
    return [st["roles"] for st in path]


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("rules")
    p.add_argument("--depth", type=int, default=4)
    p.add_argument("--out")
    args = p.parse_args()
    cert = search(Engine(load_rules(args.rules)), depth=args.depth)
    txt = json.dumps(cert, indent=1, default=list)
    if args.out:
        open(args.out, "w").write(txt)
    print(f"reachable={cert['reachable']} paths={len(cert['paths'])} sale_paths={len(cert['sale_paths'])} "
          f"expanded={cert['states_expanded']}")
    for p_ in cert["paths"][:10]:
        print("  " + " | ".join(f"{st['action']} {st['used']}" for st in p_))


def entry_step(path):
    """The step that puts the tracked asset into an unrestricted entity."""
    for st in path:
        if st["roles"].endswith("->unrestricted"):
            return st
    return path[-1]


def classify(path):
    """'uncapped-entry' if the step into the unrestricted entity is permitted in every category it
    triggers by at least one uncapped exception; otherwise 'capped-entry'."""
    st = entry_step(path)
    return "uncapped-entry" if st["capacity"] and all(c == "uncapped" for c in st["capacity"].values()) else "capped-entry"


def load_universe(path):
    with open(path) as f:
        doc = yaml.safe_load(f)
    u = default_universe()
    u.facts = doc.get("facts", [])
    u.condition_status = doc.get("condition_status", [])
    return u
