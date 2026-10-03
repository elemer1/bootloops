"""Engine, linter and control mechanics on a 7-clause synthetic contract with a known trapdoor."""
import copy
from pathlib import Path

import yaml

from lmt.engine import Engine, load_rules, search, skeleton, validate
from lmt.lint import lint
from lmt.source import load
from lmt.tools import overlay, path_signature, perturb, perturbed_universe, remove

HERE = Path(__file__).parent
RULES = load_rules(HERE / "synth_trapdoor.yaml")
BLOCKER = yaml.safe_load(open(HERE / "synth_blocker.yaml"))
SRC = load("synth_trapdoor")


def test_lint_clean_and_full_coverage():
    assert lint(RULES, SRC) == []


def test_lint_catches_paraphrased_quote():
    d = copy.deepcopy(RULES)
    d["rules"][2]["cite"]["quote"] = "Investments by a Loan Party into another Loan Party"
    assert any("quote not found verbatim" in f for f in lint(d, SRC))


def test_lint_catches_dropped_clause():
    d = remove(RULES, ["1.1(a)"])
    assert any("COVERAGE: clause 1.1(a)" in f for f in lint(d, SRC))


def test_lint_foreign_fails_by_name():
    d = copy.deepcopy(RULES)
    d["agreement"] = "jcrew2014"
    assert lint(d, SRC)[0].startswith("FOREIGN")


def test_trapdoor_found():
    cert = search(Engine(RULES))
    assert cert["reachable"]
    assert ["guarantor->nlp_rs", "nlp_rs->unrestricted"] in [skeleton(p) for p in cert["paths"]]


def test_blocker_gives_unreachable_certificate():
    cert = search(Engine(validate(overlay(RULES, BLOCKER))))
    assert not cert["reachable"]
    assert any("prohibited by SYN.blocker" in r for rs in cert["denials"].values() for r in rs)
    assert cert["states_expanded"] > 0


def test_removing_trapdoor_clause_closes_path():
    assert not search(Engine(remove(RULES, ["1.1(c)"])))["reachable"]


def test_funded_by_is_enforced():
    # without the funding link, an nlp_rs that did not receive the asset under 1.1(b) cannot use 1.1(c)
    d = copy.deepcopy(RULES)
    for r in d["rules"]:
        if r["id"] == "1.1(b)":
            r["counterparty"] = ["guarantor"]  # 1.1(b) no longer reaches nlp_rs
    assert not search(Engine(d))["reachable"]


def test_perturbation_invariance():
    base = path_signature(search(Engine(RULES)))
    for seed in range(5):
        d, idmap = perturb(RULES, seed)
        cert = search(Engine(d, perturbed_universe(seed)))
        assert path_signature(cert, idmap) == base
