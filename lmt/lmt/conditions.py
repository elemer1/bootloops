"""Conditions on rules: two dimensions, TYPE (how it is handled) and STATUS (what is known).

A rule's `conditions` entry is either a legacy string, read as {type: unknown, status: assumed},
or an object {text, type, status, source?, assumption?} with
    type   in HARD | QUANT | INTERP | PROCEDURAL | DISCRETION | unknown
    status in proven | refuted | assumed | unknown

Status is resolved in this order (first match wins):
    1. scenario `condition_status` [{pattern, status, why, source}]  (regex on the text)
    2. scenario `facts` with holds: false                            -> refuted
    3. the status written on the condition object
    4. legacy string                                                 -> assumed

Semantics (verify.py implements the same rules with its own code):
    refuted -> the rule is unavailable
    unknown -> a path relying on it can at best be indeterminate, never a candidate
    assumed -> a path may be a candidate; the condition is listed as a dependency
    proven  -> not a dependency
A PROCEDURAL condition is never satisfied by default: its status is whatever the inputs say.
"""
import re

RANK = {"proven": 0, "assumed": 1, "unknown": 2, "refuted": 3}
TYPES = {"HARD", "QUANT", "INTERP", "PROCEDURAL", "DISCRETION", "unknown"}


def normalize(cond):
    if isinstance(cond, str):
        return {"text": cond, "type": "unknown", "status": "assumed", "source": "legacy free-text condition"}
    c = dict(cond)
    c.setdefault("type", "unknown")
    c.setdefault("status", "assumed")
    if c["type"] not in TYPES or c["status"] not in RANK:
        raise ValueError(f"bad condition type/status: {cond!r}")
    return c


class Resolver:
    def __init__(self, condition_status=None, facts=None):
        self.overrides = list(condition_status or [])
        self.refuting = [f for f in (facts or []) if not f.get("holds", True)]

    def resolve(self, cond):
        c = normalize(cond)
        for o in self.overrides:
            if re.search(o["pattern"], c["text"], re.I):
                return {**c, "status": o["status"], "source": o.get("source") or o.get("why", "scenario")}
        for f in self.refuting:
            if re.search(f["pattern"], c["text"], re.I):
                return {**c, "status": "refuted", "source": f.get("why", "scenario fact")}
        return c

    def rule_conditions(self, rule):
        return [self.resolve(c) for c in rule.get("conditions") or []]

    def rule_status(self, rule):
        cs = self.rule_conditions(rule)
        worst = max((RANK[c["status"]] for c in cs), default=0)
        return [k for k, v in RANK.items() if v == worst][0], cs


def worst(statuses):
    m = max((RANK[s] for s in statuses), default=0)
    return [k for k, v in RANK.items() if v == m][0]
