"""Phase 0.5 regression tests: one minimal synthetic contract per verification defect.

NEGATIVE tests expose a defect: they must FAIL on the pinned Phase 0 commit (f7a8969) and
pass after the fix. POSITIVE controls must pass both before and after. NEW-API tests check
the verdict vocabulary introduced by the fix and are expected to fail before it only because
the vocabulary did not exist.

Each contract uses the default six-entity universe (H, B, G, Nd, Nf, U); the tracked asset
starts at G (a guarantor), encumbered.
"""
import copy

import pytest
import yaml

from lmt import certify as certify_mod
from lmt.engine import Engine, default_universe, search, validate
from lmt.ledger import check_path, funded_by_map

Q = {"clause": "SYN", "quote": "synthetic"}


def rule(rid, **kw):
    r = {"id": rid, "cite": Q, **kw}
    return r


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


def feasible_paths(doc, value, pools, rule_pools, depth):
    cert = search(Engine(doc, default_universe()), depth=depth)
    fb = funded_by_map(doc)
    return [p for p in cert["paths"] if check_path(p, value, pools, rule_pools, fb)["feasible"]]


def shapes(paths):
    return {tuple(st["roles"] for st in p) for p in paths}


# ---------------------------------------------------------------- defect 1: pruning (NEGATIVE)

PRUNE = contract([
    exc("k", ["guarantor", "nlp_rs"], ["borrower", "unrestricted"], "capped"),
    exc("u1", ["guarantor"], ["holdings"], "unlimited"),
    exc("u2", ["holdings"], ["borrower"], "unlimited"),
    exc("u", ["borrower"], ["nlp_rs"], "unlimited"),
    rule("no_direct", kind="prohibition", action="transfer", actor=["guarantor"], counterparty=["unrestricted"]),
])


def test_negative_pruning_keeps_the_longer_capacity_saving_path():
    """Short route G->B(k)->Nd(u)->U(k) needs 200 from a 100 pool; the longer route
    G->H(u1)->B(u2)->Nd(u)->U(k) needs only 100. Both reach the same state at Nd, so a
    state-only prune drops the longer, feasible one."""
    paths = feasible_paths(PRUNE, 100, {"P": 100}, {"k": ["P"]}, depth=4)
    assert ("guarantor->holdings", "holdings->borrower", "borrower->nlp_rs", "nlp_rs->unrestricted") in shapes(paths)


# ---------------------------------------------------------------- defect 2: funded_by

def funded(pf, pg, designation=False):
    rules = [
        exc("f1", ["guarantor"], ["nlp_rs"], "capped"),
        exc("g", ["guarantor"], ["nlp_rs"], "capped"),
        exc("t", ["nlp_rs"], ["unrestricted"], "unlimited", funded_by=["f1"]),
    ]
    if designation:  # only the provenance test needs designations; elsewhere they would add other routes
        rules += [
            rule("char.designate", kind="characterization", action="designate", triggers=["designation"]),
            rule("desig", kind="exception", category="designation", action="designate", actor=["borrower"],
                 counterparty=["nlp_rs"], capacity="unlimited"),
            rule("no_owner_designation", kind="prohibition", action="designate", actor=["any"],
                 counterparty=["any"], owns_tracked_asset=True),
        ]
    doc = contract(rules)
    return doc, {"PF": pf, "PG": pg}, {"f1": ["PF"], "g": ["PG"]}


def test_positive_funded_by_eligible_source_suffices_despite_other_rules():
    doc, pools, rp = funded(100, 100)
    paths = feasible_paths(doc, 100, pools, rp, depth=2)
    assert ("guarantor->nlp_rs", "nlp_rs->unrestricted") in shapes(paths)


def test_negative_funded_by_label_overlap_does_not_unlock_more_than_the_eligible_amount():
    """Total capacity (1 + 100) covers 100, but only 1 can come from the eligible basket f1.
    A booking {f1, g} must not let 7.02(t)-style rule t carry the full 100 onward."""
    doc, pools, rp = funded(1, 100)
    paths = feasible_paths(doc, 100, pools, rp, depth=2)
    assert paths == []


def test_positive_funded_by_provenance_survives_an_unrelated_designation():
    """Inbound transfer G->Nd under f1, then designate a different entity, then Nd->U under t.
    (Designating the asset's own holder is prohibited here, so the only routes go through t.)"""
    doc, pools, rp = funded(100, 100, designation=True)
    paths = feasible_paths(doc, 100, pools, rp, depth=3)
    kinds = [[st["action"].split(" ")[0] for st in p] for p in paths]
    assert ["transfer[contribution]", "designate", "transfer[contribution]"] in kinds


# ---------------------------------------------------------------- defects 3 and 4: certify outcomes

def write_case(tmp_path, doc, pools, rule_pools, value=100):
    rp = tmp_path / "rules.yaml"
    sp = tmp_path / "scenario.yaml"
    d = copy.deepcopy(doc)
    d["assumptions"] = {}
    rp.write_text(yaml.safe_dump(d, sort_keys=False))
    sp.write_text(yaml.safe_dump({"facts": [], "capacity": {"pools": pools, "rule_pools": rule_pools,
                                                            "values": {"v": value}}}))
    return str(rp), str(sp)


DIRECT = contract([exc("d", ["guarantor"], ["unrestricted"], "capped")])


def test_negative_verifier_disagreement_blocks_every_verdict(tmp_path, monkeypatch):
    """Inject a broken engine-side ledger that calls every path feasible. The independent
    verifier disagrees (pool P is only 50), so no verdict may be issued."""
    rp, sp = write_case(tmp_path, DIRECT, {"P": 50}, {"d": ["P"]})

    def broken(path, value, pools, rule_pools, *a, **k):
        return {"feasible": True, "status": "feasible", "demand": value, "routed": value,
                "steps": [], "allocation": {}, "unpriced": []}

    monkeypatch.setattr(certify_mod, "check_path", broken)
    certs = certify_mod.certificates(rp, sp, depth=1)
    assert certs and all(c["verdict"] == "VERIFICATION_FAILED" for c in certs)
    assert not any("witness" in c for c in certs)


def test_negative_unpriced_basket_is_not_proof_of_non_reachability(tmp_path):
    """The only route uses a capped basket with no known capacity: the answer is unknown."""
    rp, sp = write_case(tmp_path, DIRECT, {}, {})
    certs = certify_mod.certificates(rp, sp, depth=1)
    assert [c["verdict"] for c in certs] == ["INDETERMINATE"]


# ---------------------------------------------------------------- new verdict vocabulary / aggregation

def test_new_api_confirmed_path_is_reported_even_if_another_path_is_unknown(tmp_path):
    doc = contract([exc("d", ["guarantor"], ["unrestricted"], "capped"),
                    exc("e", ["guarantor"], ["unrestricted"], "capped")])
    rp, sp = write_case(tmp_path, doc, {"P": 100}, {"d": ["P"]})   # e is unpriced
    certs = certify_mod.certificates(rp, sp, depth=1)
    assert [c["verdict"] for c in certs] == ["CANDIDATE_PATH"]


def test_new_api_relaxed_only_feasibility_never_becomes_a_candidate(tmp_path):
    rp, sp = write_case(tmp_path, DIRECT, {"P": 10}, {"d": ["P"]})  # d priced at 10 < 100
    doc = contract([exc("d", ["guarantor"], ["unrestricted"], "capped"),
                    exc("e", ["guarantor"], ["unrestricted"], "capped")])
    rp, sp = write_case(tmp_path, doc, {"P": 10}, {"d": ["P"]})   # only unpriced e could carry 100
    certs = certify_mod.certificates(rp, sp, depth=1)
    assert [c["verdict"] for c in certs] == ["INDETERMINATE"]


def test_new_api_priced_and_insufficient_everywhere_is_bounded_non_reachability(tmp_path):
    rp, sp = write_case(tmp_path, DIRECT, {"P": 10}, {"d": ["P"]})
    certs = certify_mod.certificates(rp, sp, depth=1)
    assert [c["verdict"] for c in certs] == ["BOUNDED_NON_REACHABILITY"]


# ---------------------------------------------------------------- source eligibility, below the engine

def _step(kind, src, dst, booked, capped, holder=None):
    return {"action": f"{kind} {src}->{dst}", "kind": "transfer", "src": src, "dst": dst, "entity": "",
            "holder": holder or src, "roles": "x->y", "used": {"investments": booked},
            "designated": booked, "capacity": {"investments": "capped" if capped else "uncapped"},
            "effects": [], "assumptions": []}


def test_ledger_rejects_ineligible_inbound_booking_even_with_shared_pool():
    """Inbound booked {f1, g}; onward rule t requires f1 only. f1 and g share pool P (100): the pool
    is big enough, but eligibility is decided on rule nodes, so the ledger must reject."""
    path = [_step("transfer[contribution]", "G", "Nd", ["f1", "g"], True),
            _step("transfer[contribution]", "Nd", "U", ["t"], False)]
    out = check_path(path, 100, {"P": 100}, {"f1": ["P"], "g": ["P"]}, funded_by={"t": ["f1"]})
    assert out["status"] == "infeasible"


def test_ledger_inbound_is_the_transfer_to_the_current_holder_not_the_previous_action():
    path = [_step("transfer[contribution]", "G", "Nd", ["f1"], True),
            {**_step("designate", "", "", [], False), "kind": "designate", "entity": "Nf", "holder": "Nd",
             "used": {}, "designated": [], "capacity": {}},
            _step("transfer[contribution]", "Nd", "U", ["t"], False)]
    out = check_path(path, 100, {"PF": 100}, {"f1": ["PF"]}, funded_by={"t": ["f1"]})
    assert out["status"] == "feasible"


def test_verifier_independently_rejects_label_overlap():
    from lmt import verify
    doc, pools, rp = funded(1, 100)
    chk = verify.Checker(doc, {"facts": []}, set())
    fb = {"t": ["f1"]}
    assert [p for p in chk.paths(2) if verify.hall_status(p, 100, pools, rp, fb) == "feasible"] == []


# ---------------------------------------------------------------- review of 3cfc54e: P1 (a) declared pool, unknown amount

def test_negative_declared_pool_with_unknown_amount_is_not_non_reachability(tmp_path):
    """Rule d draws on pool P, whose amount is unknown (null). Not proof of non-reachability."""
    rp, sp = write_case(tmp_path, DIRECT, {"P": None}, {"d": ["P"]})
    certs = certify_mod.certificates(rp, sp, depth=1)
    assert [c["verdict"] for c in certs] == ["INDETERMINATE"]


def test_config_error_pool_referenced_but_not_declared_is_refused(tmp_path):
    rp, sp = write_case(tmp_path, DIRECT, {}, {"d": ["P"]})
    with pytest.raises(Exception) as ei:
        certify_mod.certificates(rp, sp, depth=1)
    assert type(ei.value).__name__ == "CapacityConfigError"
    assert "P" in str(ei.value)


def test_shared_unknown_pool_keeps_its_identity(tmp_path):
    doc = contract([exc("d", ["guarantor"], ["unrestricted"], "capped"),
                    exc("e", ["guarantor"], ["unrestricted"], "capped")])
    rp, sp = write_case(tmp_path, doc, {"P": None}, {"d": ["P"], "e": ["P"]})
    certs = certify_mod.certificates(rp, sp, depth=1)
    assert [c["verdict"] for c in certs] == ["INDETERMINATE"]
    assert certs[0]["unknowns"] == ["pool P: amount unknown"]


def test_positive_known_pools_unchanged(tmp_path):
    rp, sp = write_case(tmp_path, DIRECT, {"P": 100}, {"d": ["P"]})
    assert [c["verdict"] for c in certify_mod.certificates(rp, sp, depth=1)] == ["CANDIDATE_PATH"]


# ---------------------------------------------------------------- review of 3cfc54e: P1 (b) entity-level signatures

SYMMETRIC = contract([exc("a", ["guarantor"], ["nlp_rs"], "unlimited"),
                      exc("b", ["nlp_rs"], ["unrestricted"], "unlimited")])


def test_negative_dropping_a_same_role_different_entity_path_fails_verification(tmp_path, monkeypatch):
    """G->Nd->U and G->Nf->U have the same role shape. If the engine loses every path through Nf,
    the verifier (which still has it) must block the verdict."""
    rp, sp = write_case(tmp_path, SYMMETRIC, {}, {})
    real = certify_mod.search

    def lossy(engine, depth=4, **kw):
        cert = real(engine, depth=depth, **kw)
        cert["paths"] = [p for p in cert["paths"] if not any("Nf" in st["action"] for st in p)]
        return cert

    monkeypatch.setattr(certify_mod, "search", lossy)
    certs = certify_mod.certificates(rp, sp, depth=2)
    assert [c["verdict"] for c in certs] == ["VERIFICATION_FAILED"]


def test_new_api_symmetric_paths_counted_per_entity_without_tampering(tmp_path):
    rp, sp = write_case(tmp_path, SYMMETRIC, {}, {})
    certs = certify_mod.certificates(rp, sp, depth=2)
    assert [c["verdict"] for c in certs] == ["CANDIDATE_PATH"]
    assert certs[0]["independent_verifier"]["engine"]["feasible"] == 2
