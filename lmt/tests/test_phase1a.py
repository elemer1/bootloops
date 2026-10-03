"""Phase 1a: AA threshold queries, condition type x status, certificate split.

Synthetic contracts on the default six-entity universe; the asset starts at G (a guarantor).
"""
import copy
import random

import pytest
import yaml

from lmt import certify as certify_mod
from lmt.engine import validate

Q = {"clause": "SYN", "quote": "synthetic"}


def rule(rid, **kw):
    return {"id": rid, "cite": Q, **kw}


def contract(rules):
    base = [
        rule("char.contribution", kind="characterization", action="transfer", forms=["contribution"],
             triggers=["investments"]),
        rule("release", kind="effect", on="transfer", when={"counterparty": ["nlp_rs", "unrestricted"]},
             then="release_lien"),
    ]
    return validate({"agreement": "synthetic", "rules": base + rules})


def exc(rid, actor, cp, capacity, **kw):
    return rule(rid, kind="exception", category="investments", action="transfer", actor=actor,
                counterparty=cp, assets=["any"], capacity=capacity, **kw)


def run(tmp_path, doc, pools, rule_pools, value=100, aa="AA", condition_status=None, depth=1):
    d = copy.deepcopy(doc)
    d["assumptions"] = {}
    rp, sp = tmp_path / "rules.yaml", tmp_path / "scenario.yaml"
    rp.write_text(yaml.safe_dump(d, sort_keys=False))
    sc = {"facts": [], "condition_status": condition_status or [],
          "capacity": {"pools": pools, "rule_pools": rule_pools, "values": {"v": value}}}
    if aa:
        sc["aa_parameter"] = aa
    sp.write_text(yaml.safe_dump(sc))
    return certify_mod.certificates(str(rp), str(sp), depth=depth)


def aa_of(c):
    return {k: v for k, v in c["dependencies"]["aa"].items() if k not in ("premise", "parameter")}


# ---------------------------------------------------------------- the four threshold outcomes

def test_threshold_proven_minimum(tmp_path):
    doc = contract([exc("d", ["guarantor"], ["unrestricted"], "capped")])
    [c] = run(tmp_path, doc, {"P": 60, "AA": None}, {"d": ["P", "AA"]})
    assert aa_of(c) == {"result": "PROVEN_MIN_AA", "min_aa": 40}
    assert c["verdict"] == "INDETERMINATE"           # AA itself is unknown, so no confirmed path yet
    assert "premise" in c["dependencies"]["aa"]


def test_threshold_lower_bound_and_sufficient_upper_bound(tmp_path):
    doc = contract([exc("d", ["guarantor"], ["unrestricted"], "capped"),
                    exc("e", ["guarantor"], ["unrestricted"], "capped")])
    [c] = run(tmp_path, doc, {"P": 60, "Q": None, "AA": None}, {"d": ["P", "AA"], "e": ["Q", "AA"]})
    assert aa_of(c) == {"result": "BOUNDS", "lower_bound": 0, "sufficient_upper_bound": 40}


def test_threshold_no_aa_suffices(tmp_path):
    doc = contract([exc("d", ["guarantor"], ["unrestricted"], "capped")])
    [c] = run(tmp_path, doc, {"P": 60, "AA": None}, {"d": ["P"]})
    assert aa_of(c) == {"result": "NO_AA_SUFFICES"}
    assert c["verdict"] == "BOUNDED_NON_REACHABILITY"


def test_threshold_indeterminate_when_only_an_unconfirmed_route_exists(tmp_path):
    cond = {"text": "officer certificate delivered", "type": "PROCEDURAL", "status": "unknown"}
    doc = contract([exc("e", ["guarantor"], ["unrestricted"], "capped", conditions=[cond])])
    [c] = run(tmp_path, doc, {"AA": None}, {"e": ["AA"]})
    assert aa_of(c) == {"result": "INDETERMINATE", "lower_bound": 100}
    assert c["verdict"] == "INDETERMINATE"


# ---------------------------------------------------------------- bisection vs Hall, randomized

def random_contract(rng):
    rules = []
    hops = [("guarantor", "nlp_rs"), ("nlp_rs", "unrestricted"), ("guarantor", "unrestricted"),
            ("guarantor", "borrower"), ("borrower", "nlp_rs")]
    names = []
    for i, (a, b) in enumerate(hops):
        for k in range(rng.randint(0, 2)):
            rid = f"r{i}{k}"
            capped = rng.random() < 0.75
            rules.append(exc(rid, [a], [b], "capped" if capped else "unlimited"))
            if capped:
                names.append(rid)
    pools = {"AA": None, "P": rng.choice([0, 30, 60, 100]), "Q": rng.choice([None, 20, 50])}
    rule_pools = {r: rng.sample(["P", "Q", "AA"], rng.randint(1, 2)) for r in names if rng.random() < 0.9}
    return contract(rules), pools, rule_pools


@pytest.mark.parametrize("seed", range(30))
def test_bisection_and_hall_thresholds_agree_on_random_contracts(tmp_path, seed):
    rng = random.Random(seed)
    doc, pools, rule_pools = random_contract(rng)
    for c in run(tmp_path, doc, pools, rule_pools, value=rng.choice([50, 100]), depth=3):
        assert c["independent_verifier"]["aa_thresholds_agree"], seed
        assert c["verdict"] != "VERIFICATION_FAILED"


def test_wrong_threshold_blocks_everything(tmp_path, monkeypatch):
    real = certify_mod.path_thresholds

    def off_by_one(*a, **k):
        x_c, x_r = real(*a, **k)
        return (None if x_c is None else x_c + 1), x_r

    monkeypatch.setattr(certify_mod, "path_thresholds", off_by_one)
    doc = contract([exc("d", ["guarantor"], ["unrestricted"], "capped")])
    [c] = run(tmp_path, doc, {"P": 60, "AA": None}, {"d": ["P", "AA"]})
    assert c["verdict"] == "VERIFICATION_FAILED"
    assert c["dependencies"] is None and "witness" not in c


# ---------------------------------------------------------------- condition type x status

def cond_contract(cond):
    return contract([exc("d", ["guarantor"], ["unrestricted"], "capped", conditions=[cond])])


POOLS, RP = {"P": 100}, {"d": ["P"]}


def test_refuted_condition_disables_the_rule(tmp_path):
    doc = cond_contract({"text": "no Event of Default", "type": "HARD"})
    [c] = run(tmp_path, doc, POOLS, RP, aa=None,
              condition_status=[{"pattern": "Event of Default", "status": "refuted", "why": "EoD continuing"}])
    assert c["verdict"] == "BOUNDED_NON_REACHABILITY"


def test_unknown_condition_cannot_be_a_candidate(tmp_path):
    doc = cond_contract({"text": "no Event of Default", "type": "HARD", "status": "unknown"})
    [c] = run(tmp_path, doc, POOLS, RP, aa=None)
    assert c["verdict"] == "INDETERMINATE"
    assert any("no Event of Default" in u for u in c["unknowns"])


def test_assumed_condition_allows_a_candidate_and_is_listed(tmp_path):
    doc = cond_contract({"text": "no Event of Default", "type": "HARD", "status": "assumed"})
    [c] = run(tmp_path, doc, POOLS, RP, aa=None)
    assert c["verdict"] == "CANDIDATE_PATH"
    [d] = c["dependencies"]["conditions"]
    assert (d["text"], d["type"], d["status"]) == ("no Event of Default", "HARD", "assumed")


def test_legacy_string_is_listed_as_unknown_type_assumed(tmp_path):
    doc = cond_contract("no Event of Default")
    [c] = run(tmp_path, doc, POOLS, RP, aa=None)
    assert c["verdict"] == "CANDIDATE_PATH"
    [d] = c["dependencies"]["conditions"]
    assert (d["type"], d["status"]) == ("unknown", "assumed")


def test_procedural_is_not_satisfied_by_default(tmp_path):
    doc = cond_contract({"text": "fairness letter delivered", "type": "PROCEDURAL", "status": "unknown"})
    [c] = run(tmp_path, doc, POOLS, RP, aa=None)
    assert c["verdict"] == "INDETERMINATE"


def test_proven_condition_is_not_a_pending_dependency(tmp_path):
    doc = cond_contract({"text": "no Event of Default", "type": "HARD", "status": "proven", "source": "x"})
    [c] = run(tmp_path, doc, POOLS, RP, aa=None)
    assert c["verdict"] == "CANDIDATE_PATH"
    assert [d["status"] for d in c["dependencies"]["conditions"]] == ["proven"]


def test_no_conditions_reads_as_no_further_open_conditions(tmp_path):
    doc = contract([exc("d", ["guarantor"], ["unrestricted"], "capped")])
    [c] = run(tmp_path, doc, POOLS, RP, aa=None)
    assert c["dependencies"]["conditions"] == [certify_mod.NO_PENDING]
    assert "UNCONDITIONAL" not in str(c)
