"""Certificates per (interpretation profile, asset value), gated by the independent verifier.

    python3 -m lmt.certify [--depth 3] [--out reports/]      # exit 1 if any query fails verification

Per path, the ledger returns feasible / indeterminate / infeasible (ledger.py). Per query:

    at least one path feasible in the confirmed model     -> CANDIDATE_PATH (that path is output)
    none feasible, but some path depends on an unknown    -> INDETERMINATE (the unknowns are listed)
    every path infeasible even in the relaxed model       -> BOUNDED_NON_REACHABILITY

The engine (engine.py + ledger.py) and the verifier (verify.py) must produce identical
signature sets for both the feasible and the indeterminate paths. Otherwise the verdict is
VERIFICATION_FAILED and nothing else is issued: no path, no non-reachability statement.

A BOUNDED_NON_REACHABILITY verdict says: for this model (rules, assumptions, facts), initial
state, entity universe and depth, no path reaches the goal even under the optimistic bounds.
It is never a statement that the contract is safe.
"""
import argparse
import hashlib
import json
import os
import sys

import yaml

from . import verify
from .engine import Engine, classify, load_rules, load_universe, search, skeleton, validate
from .ledger import CapacityConfigError, check_path, funded_by_map, validate_capacity
from .threshold import PREMISE, aggregate, path_thresholds

GOAL = "tracked IP owned by an Unrestricted Subsidiary, lenders' lien released, no fair-value sale on the path"
NO_PENDING = "no further open conditions, within the stated model, initial state and fact inputs"


def sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=list).encode()).hexdigest()


def esig(p):
    """Entity-level signature from the engine's action labels ('transfer[form] SRC->DST' / 'designate E')
    plus the booking. Must equal verify.signature, which builds the same string independently."""
    return tuple((st["action"], tuple(sorted(st.get("designated") or []))) for st in p)


def certificates(rules_path, scenario_path, depth=3, overlay_doc=None, label="base"):
    from .tools import overlay as _ov
    doc = load_rules(rules_path)
    if overlay_doc:
        doc = validate(_ov(doc, overlay_doc))
    sc = yaml.safe_load(open(scenario_path))
    cap = sc["capacity"]
    validate_capacity(cap["pools"], cap["rule_pools"])   # refuse before any verdict is computed
    fb = funded_by_map(doc)
    u = load_universe(scenario_path)
    ver = verify.check(doc, scenario_path, depth)
    aa = sc.get("aa_parameter")
    unknown_pools = sorted(p for p, a in cap["pools"].items() if a is None)
    out = []
    for prof in sorted(ver, key=lambda k: (len(k[0]), k)):
        assumptions, vname = prof
        cert = search(Engine(doc, u, set(assumptions)), depth=depth)
        value = cap["values"][vname]
        judged = [(p, check_path(p, value, cap["pools"], cap["rule_pools"], fb)) for p in cert["paths"]]
        feas = [(p, l) for p, l in judged if l["status"] == "feasible"]
        indet = [(p, l) for p, l in judged if l["status"] == "indeterminate"]
        e_f, e_i = {esig(p) for p, _ in feas}, {esig(p) for p, _ in indet}
        v_f, v_i = ver[prof]["feasible"], ver[prof]["indeterminate"]
        agree = e_f == v_f and e_i == v_i
        aa_result, thr_agree = None, True
        if aa:
            e_thr = {esig(p): path_thresholds(p, value, cap["pools"], cap["rule_pools"], fb, aa) for p in cert["paths"]}
            thr_agree = e_thr == ver[prof]["thresholds"]
            aa_result = {**aggregate(list(e_thr.values())), "parameter": aa, "premise": PREMISE}
        c = {
            "label": label,
            "model": {"rules_sha256": sha(doc), "assumptions_on": list(assumptions),
                      "assumption_text": {a: doc["assumptions"][a] for a in assumptions},
                      "scenario_facts": sc.get("facts", []),
                      "condition_status": sc.get("condition_status", []), "goal": GOAL},
            "bound": {"depth": depth, "entities": u.entities, "start_owner": u.start_owner,
                      "mode": "reference (no pruning)"},
            "value": {"name": vname, "usd": value},
            "independent_verifier": {"agrees": agree and thr_agree, "paths_agree": agree,
                                     "aa_thresholds_agree": thr_agree,
                                     "engine": {"feasible": len(e_f), "indeterminate": len(e_i)},
                                     "verifier": {"feasible": len(v_f), "indeterminate": len(v_i)}},
            "structural_paths": len(cert["paths"]),
        }
        deps = {"interpretation": list(assumptions), "aa": aa_result,
                "missing_facts": [f"pool {p}: amount unknown" for p in unknown_pools]}
        if not (agree and thr_agree):
            c["verdict"] = "VERIFICATION_FAILED"
            c["disagreement"] = {"feasible_only_engine": len(e_f - v_f), "feasible_only_verifier": len(v_f - e_f),
                                 "indeterminate_only_engine": len(e_i - v_i),
                                 "indeterminate_only_verifier": len(v_i - e_i),
                                 "aa_thresholds_agree": thr_agree}
            deps = None                       # nothing is issued, not even the threshold
        elif feas:
            p, led = sorted(feas, key=lambda x: (len(x[0]), esig(x[0])))[0]
            c["verdict"] = "CANDIDATE_PATH"
            c["witness"] = {"shape": skeleton(p), "class": classify(p), "allocation_usd": led["allocation"],
                            "steps": [{k: st[k] for k in ("action", "roles", "used", "designated", "capacity",
                                                           "effects")} for st in p]}
            conds = []
            for st in p:
                for cd in st.get("conditions", []):
                    if cd not in conds:
                        conds.append(cd)
            deps["conditions"] = conds or [NO_PENDING]
            c["other_paths"] = {"feasible": len(feas), "indeterminate": len(indet)}
        elif indet:
            c["verdict"] = "INDETERMINATE"
            c["unknowns"] = sorted({u_ for _, l in indet for u_ in l.get("unknowns", [])}) or \
                ["deemed-Investment amount of a designated entity that does not hold the asset"]
            c["indeterminate_paths"] = len(indet)
        else:
            c["verdict"] = "BOUNDED_NON_REACHABILITY"
            c["why_not"] = {"structural_paths_all_infeasible_even_relaxed": len(cert["paths"]),
                            "sample_denials": dict(list(cert["denials"].items())[:12])}
        c["search_result"] = c["verdict"]
        c["dependencies"] = deps
        out.append(c)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--out", default="reports")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    runs = [("base", None)] + [(f"blocker_{n}", yaml.safe_load(open(f"rules/overlay_blocker_{n}.yaml")))
                               for n in ("cpi2020", "weak")]
    failed = 0
    for label, ov in runs:
        try:
            certs = certificates("rules/jcrew2014.yaml", "rules/scenario_jcrew2016.yaml", a.depth, ov, label)
        except CapacityConfigError as e:
            print(f"REFUSED (invalid capacity input, no certificate written): {e}")
            sys.exit(2)
        json.dump(certs, open(os.path.join(a.out, f"certificates_{label}.json"), "w"), indent=1, default=list)
        for c in certs:
            failed += c["verdict"] == "VERIFICATION_FAILED"
            aa = (c.get("dependencies") or {}).get("aa") or {}
            aa_s = {k: v for k, v in aa.items() if k not in ("premise", "parameter")}
            print(f"{label:16s} {'+'.join(c['model']['assumptions_on']) or '(none)':9s} {c['value']['name']:18s} "
                  f"{c['verdict']:26s} AA {aa_s}"
                  + (f"  {' | '.join(c['witness']['shape'])}" if 'witness' in c else ""))
    if failed:
        print(f"{failed} quer(y/ies) failed independent verification; no verdict issued for them")
        sys.exit(1)


if __name__ == "__main__":
    main()
