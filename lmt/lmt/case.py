"""Run the J.Crew backtest across interpretation profiles and asset values.

    python3 -m lmt.case [--depth 3] [--json out.json]
"""
import argparse
import itertools
import json

import yaml

from .engine import Engine, classify, load_rules, load_universe, search, skeleton
from .ledger import check_path, funded_by_map

RULES = "rules/jcrew2014.yaml"
SCENARIO = "rules/scenario_jcrew2016.yaml"


def profiles(doc):
    ids = sorted((doc.get("assumptions") or {}).keys())
    for n in range(len(ids) + 1):
        for combo in itertools.combinations(ids, n):
            yield frozenset(combo)


def run(rules_doc, scenario_path=SCENARIO, depth=3):
    sc = yaml.safe_load(open(scenario_path))
    cap = sc["capacity"]
    u = load_universe(scenario_path)
    rows = []
    fb = funded_by_map(rules_doc)
    for prof in profiles(rules_doc):
        cert = search(Engine(rules_doc, u, prof), depth=depth)
        for vname, value in cap["values"].items():
            feas = []
            for p in cert["paths"]:
                led = check_path(p, value, cap["pools"], cap["rule_pools"], fb)
                if led["feasible"]:
                    feas.append((p, led))
            rows.append({
                "assumptions": sorted(prof), "value": vname, "value_usd": value,
                "structural_paths": len(cert["paths"]),
                "feasible_paths": len(feas),
                "feasible_skeletons": sorted({" | ".join(skeleton(p)) + f"  [{classify(p)}]" for p, _ in feas}),
                "example": [{"action": st["action"], "roles": st["roles"], "used": st["used"],
                             "capacity": st["capacity"]} for st in feas[0][0]] if feas else None,
                "states_expanded": cert["states_expanded"],
            })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--json")
    a = ap.parse_args()
    rows = run(load_rules(RULES), depth=a.depth)
    for r in rows:
        print(f"{'+'.join(r['assumptions']) or '(none)':10s} {r['value']:18s} structural={r['structural_paths']:3d} "
              f"feasible={r['feasible_paths']:3d}  {'; '.join(r['feasible_skeletons'])}")
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=1, default=list)


if __name__ == "__main__":
    main()
