"""Write one certificate per (interpretation profile, asset value), cross-checked by verify.py.

    python3 -m lmt.certify [--depth 3] [--out reports/]

A certificate is either a WITNESS (a capacity-feasible leakage path, every step with the
clauses that permit it, its basket booking and dollar allocation) or a BOUNDED
NON-REACHABILITY statement: for model M (rules + assumptions + scenario facts), initial
state s0, entity universe E and depth k, no capacity-feasible path reaches the goal.
It is never a statement that the contract is safe.
"""
import argparse
import hashlib
import json
import os

import yaml

from .engine import Engine, classify, load_rules, load_universe, search, skeleton
from .ledger import check_path
from . import verify

GOAL = "tracked IP owned by an Unrestricted Subsidiary, lenders' lien released, no fair-value sale on the path"


def sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=list).encode()).hexdigest()


def certificates(rules_path, scenario_path, depth=3, overlay_doc=None, label="base"):
    from .tools import overlay as _ov
    from .engine import validate
    doc = load_rules(rules_path)
    if overlay_doc:
        doc = validate(_ov(doc, overlay_doc))
    sc = yaml.safe_load(open(scenario_path))
    cap = sc["capacity"]
    u = load_universe(scenario_path)
    ver = verify.check(doc, scenario_path, depth)
    out = []
    for prof in sorted(ver, key=lambda k: (len(k[0]), k)):
        assumptions, vname = prof
        cert = search(Engine(doc, u, set(assumptions)), depth=depth)
        value = cap["values"][vname]
        feas = []
        for p in cert["paths"]:
            led = check_path(p, value, cap["pools"], cap["rule_pools"])
            if led["feasible"]:
                feas.append((p, led))
        v_set = ver[prof]
        e_set = {tuple((st["roles"], st["action"].split(" ")[0], tuple(sorted(st.get("designated") or []))) for st in p)
                 for p, _ in feas}
        minlen = min((len(s) for s in v_set), default=0)
        agree = (bool(e_set) == bool(v_set)) and e_set <= v_set and {s for s in v_set if len(s) == minlen} <= e_set
        c = {
            "label": label,
            "model": {"rules_sha256": sha(doc), "assumptions_on": list(assumptions),
                      "assumption_text": {a: doc["assumptions"][a] for a in assumptions},
                      "scenario_facts": sc.get("facts", []), "goal": GOAL},
            "bound": {"depth": depth, "entities": u.entities, "start_owner": u.start_owner,
                      "initial_state_sha256": sha(u.initial().__dict__ if hasattr(u.initial(), '__dict__') else str(u.initial()))},
            "value": {"name": vname, "usd": value},
            "verdict": "WITNESS" if feas else "BOUNDED_NON_REACHABILITY",
            "structural_paths": len(cert["paths"]),
            "states_expanded": cert["states_expanded"],
            "independent_verifier": {"agrees": agree, "verifier_feasible_signatures": len(v_set),
                                     "engine_feasible_signatures": len(e_set)},
        }
        if feas:
            p, led = sorted(feas, key=lambda x: len(x[0]))[0]
            c["witness"] = {"shape": skeleton(p), "class": classify(p), "allocation_usd": led["allocation"],
                            "steps": [{k: st[k] for k in ("action", "roles", "used", "designated", "capacity",
                                                           "effects", "assumptions")} for st in p]}
        else:
            c["why_not"] = {"structural_paths_all_capacity_infeasible": len(cert["paths"]),
                            "note": "every structural path fails the capacity ledger (Hall condition in verify.py)"
                            if cert["paths"] else "no structural path within the bound",
                            "sample_denials": dict(list(cert["denials"].items())[:12])}
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
    for label, ov in runs:
        certs = certificates("rules/jcrew2014.yaml", "rules/scenario_jcrew2016.yaml", a.depth, ov, label)
        json.dump(certs, open(os.path.join(a.out, f"certificates_{label}.json"), "w"), indent=1, default=list)
        for c in certs:
            print(f"{label:16s} {'+'.join(c['model']['assumptions_on']) or '(none)':9s} {c['value']['name']:18s} "
                  f"{c['verdict']:26s} verifier={'AGREE' if c['independent_verifier']['agrees'] else 'DISAGREE'}"
                  + (f"  {' | '.join(c['witness']['shape'])} {c['witness']['allocation_usd']}" if 'witness' in c else ""))


if __name__ == "__main__":
    main()
