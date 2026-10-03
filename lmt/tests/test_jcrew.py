"""J.Crew 2014 acceptance tests (T1-T6 + verifier agreement + capacity ledger).

Answer key (from the lenders' complaint, N.Y. Sup. Ct. Index No. 654397/2017, paras. 58-60, 82):
step 1 J. Crew International (Loan Party) -> J. Crew Cayman (Restricted Subsidiary, not a Loan
Party), as a contribution to equity capital; step 2 onward into an Unrestricted Subsidiary chain;
the company invoked 7.02(c)(iv) and (n); certified value $250M of a $347M trademark collateral.
Whether the transfer was legally permitted was never adjudicated: T1 asks only whether the
model recovers a candidate path with that structure, every transition grounded in text.
"""
from pathlib import Path

import pytest
import yaml

from lmt import verify
from lmt.closure import check as closure_check
from lmt.engine import Engine, classify, load_rules, load_universe, search, skeleton, validate
from lmt.ledger import check_path, funded_by_map
from lmt.lint import lint
from lmt.source import load
from lmt.tools import first_step_table, overlay, path_signature, perturb, perturbed_universe, remove

ROOT = Path(__file__).resolve().parent.parent
RULES = load_rules(ROOT / "rules/jcrew2014.yaml")
SCEN = ROOT / "rules/scenario_jcrew2016.yaml"
SC = yaml.safe_load(open(SCEN))
CAP = SC["capacity"]
U = load_universe(SCEN)
SRC = load("jcrew2014")
V250, V347 = CAP["values"]["company_certified"], CAP["values"]["full_trademark"]


def feasible(doc, assumptions, value, depth=3, universe=None, status="feasible"):
    cert = search(Engine(doc, universe or U, set(assumptions)), depth=depth)
    fb = funded_by_map(doc)
    return [(p, led) for p in cert["paths"]
            if (led := check_path(p, value, CAP["pools"], CAP["rule_pools"], fb))["status"] == status]


def overlay_file(name):
    return validate(overlay(RULES, yaml.safe_load(open(ROOT / f"rules/overlay_blocker_{name}.yaml"))))


# ---- T4 grounding -----------------------------------------------------------------------

@pytest.mark.parametrize("f", ["jcrew2014.yaml", "jcrew2014_A.yaml", "jcrew2014_B.yaml"])
def test_T4_every_quote_verbatim_and_full_coverage(f):
    assert lint(load_rules(ROOT / "rules" / f), SRC) == []


def test_T4_closure_every_outside_reference_declared():
    assert closure_check(RULES, SRC) == {}


def test_T4_lien_release_grounded_in_security_agreement():
    d = remove(RULES, [])
    for r in d["rules"]:
        r.pop("cites", None)
    assert any("not grounded" in f for f in lint(d, SRC))


@pytest.mark.parametrize("name", ["cpi2020", "weak", "strong"])
def test_T4_overlays_quote_their_own_text(name):
    assert lint(overlay_file(name), SRC) == []


# ---- the two blind encodings ----------------------------------------------------------------

def test_blind_encodings_agree_on_every_first_step():
    a = first_step_table(load_rules(ROOT / "rules/jcrew2014_A.yaml"), U)
    b = first_step_table(load_rules(ROOT / "rules/jcrew2014_B.yaml"), U)
    assert {k: v is None for k, v in a.items()} == {k: v is None for k, v in b.items()}


def test_blind_encodings_agree_on_leak_shapes():
    def shapes(f):
        cert = search(Engine(load_rules(ROOT / "rules" / f), U), depth=3)
        return {(tuple(skeleton(p)), classify(p)) for p in cert["paths"]}
    assert shapes("jcrew2014_A.yaml") == shapes("jcrew2014_B.yaml")


# ---- T1 recover the historical structure ------------------------------------------------------

def test_T1_candidate_path_with_historical_structure_under_A1():
    feas = feasible(RULES, {"A1"}, V250)
    two_step = [(p, led) for p, led in feas if skeleton(p) == ["guarantor->nlp_rs", "nlp_rs->unrestricted"]]
    assert two_step, "historical shape not recovered"
    p, led = two_step[0]
    assert set(p[0]["designated"]) <= {"7.02(c)(iv)", "7.02(n)", "7.02(i).nlp"}
    assert p[1]["designated"] == ["7.02(t)"]
    assert p[0]["action"].startswith("transfer[contribution]") and p[1]["action"].startswith("transfer[contribution]")
    assert sum(led["allocation"][0].values()) == V250


def test_T1_the_only_uncapped_entry_is_the_7_02_t_route():
    cert = search(Engine(RULES, U, {"A1", "A2", "A3"}), depth=3)
    for p in cert["paths"]:
        if classify(p) == "uncapped-entry":
            entry = next(st for st in p if st["roles"].endswith("->unrestricted"))
            assert entry["designated"] == ["7.02(t)"]


def test_T1_without_A1_no_feasible_leak_of_250m():
    for prof in [set(), {"A2"}, {"A3"}, {"A2", "A3"}]:
        assert feasible(RULES, prof, V250) == []


def test_T1_ledger_347m_does_not_fit_under_A1_alone_but_fits_with_A2():
    assert feasible(RULES, {"A1"}, V347) == []
    assert feasible(RULES, {"A1", "A2"}, V347)


# ---- T2 blockers -----------------------------------------------------------------------------

def test_T2_real_cpi2020_blocker_closes_every_path():
    for prof in [set(), {"A1"}, {"A1", "A2", "A3"}]:
        cert = search(Engine(overlay_file("cpi2020"), U, prof), depth=3)
        assert cert["paths"] == []
        assert any(any("prohibited by CPI." in r for r in rs) for rs in cert["denials"].values())


def test_T2b_weak_blocker_is_bypassed_through_the_non_guarantor():
    feas = feasible(overlay_file("weak"), {"A1"}, V250)
    assert any(skeleton(p) == ["guarantor->nlp_rs", "nlp_rs->unrestricted"] for p, _ in feas)


# ---- T3 remove the springboard ----------------------------------------------------------------

def test_T3_without_7_02_t_no_feasible_leak_under_any_profile():
    d = remove(RULES, ["7.02(t)"])
    for prof in [set(), {"A1"}, {"A2"}, {"A1", "A2", "A3"}]:
        assert feasible(d, prof, V250) == []


# ---- T5 foreign ------------------------------------------------------------------------------

def test_T5_rules_checked_against_another_agreement_fail_by_name():
    assert lint(RULES, load("synth_trapdoor"))[0].startswith("FOREIGN")


# ---- T6 perturbation -------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [1, 2])
def test_T6_renaming_and_shuffling_do_not_change_results(seed):
    base = search(Engine(RULES, U, {"A1"}), depth=3)
    d, idmap = perturb(RULES, seed)
    pu = perturbed_universe(seed)
    pu.facts = U.facts
    cert = search(Engine(d, pu, {"A1"}), depth=3)
    assert path_signature(cert, idmap) == path_signature(base)


# ---- independent verifier --------------------------------------------------------------------

def test_independent_verifier_agrees_on_full_path_sets():
    """Reference mode (no pruning on either side): the feasible and the indeterminate signature
    sets must be identical, with funded_by source constraints applied on both sides."""
    def esig(p):
        return tuple((st["roles"], st["action"].split(" ")[0], tuple(sorted(st.get("designated") or []))) for st in p)
    fb = funded_by_map(RULES)
    for prof in [(), ("A1",)]:
        vpaths = verify.Checker(RULES, SC, set(prof)).paths(3)
        for vname, value in CAP["values"].items():
            for status in ("feasible", "indeterminate"):
                vs = {verify.signature(p) for p in vpaths
                      if verify.hall_status(p, value, CAP["pools"], CAP["rule_pools"], fb) == status}
                es = {esig(p) for p, _ in feasible(RULES, set(prof), value, status=status)}
                assert es == vs, (prof, vname, status)
