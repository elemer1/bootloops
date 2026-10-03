"""Available Amount (AA) threshold query: what AA does a leakage path need?

Premise, stated in every result: the rules, the interpretation profile, the other facts and every
other pool are FIXED; only the amount of the AA pool varies. Under that premise feasibility is
monotone in AA, so a per-path threshold is well defined and found by integer bisection on
[0, B], where B = value x (number of capped steps) is a finite bound beyond which more AA
cannot help.

Per path: x_c = least AA making it feasible in the confirmed model (other unknown pools 0,
unknown conditions block); x_r = least AA making it feasible in the relaxed model (other unknown
pools at their bound, unknown conditions not blocking). Either may be None (no AA suffices).

Per query:
    no path feasible even relaxed at AA = B   -> NO_AA_SUFFICES (with the bottleneck)
    min x_c exists and equals min x_r         -> PROVEN_MIN_AA
    min x_c exists and exceeds min x_r        -> LOWER_BOUND (min x_r) + SUFFICIENT_UPPER_BOUND (min x_c)
    only x_r exists                           -> INDETERMINATE (lower bound min x_r, unknowns listed)

verify.py computes the same per-path thresholds analytically (Hall's condition); certify.py
compares the two and withholds the result if they differ.
"""
from .ledger import check_path

PREMISE = ("rules, interpretation profile, other facts and all other pools fixed; only the "
           "Available Amount pool varies (feasibility is monotone in it only under this premise)")


def _status(path, value, pools, rule_pools, fb, aa, x):
    p2 = dict(pools)
    p2[aa] = x
    return check_path(path, value, p2, rule_pools, fb)["status"]


def _least(path, value, pools, rule_pools, fb, aa, ok):
    n_capped = sum(1 for st in path if st["capacity"].get("investments") == "capped")
    hi = value * max(n_capped, 1)
    if not ok(_status(path, value, pools, rule_pools, fb, aa, hi)):
        return None
    lo = 0
    if ok(_status(path, value, pools, rule_pools, fb, aa, 0)):
        return 0
    while hi - lo > 1:                       # invariant: not ok at lo, ok at hi
        mid = (lo + hi) // 2
        if ok(_status(path, value, pools, rule_pools, fb, aa, mid)):
            hi = mid
        else:
            lo = mid
    return hi


def path_thresholds(path, value, pools, rule_pools, fb, aa):
    x_c = _least(path, value, pools, rule_pools, fb, aa, lambda s: s == "feasible")
    x_r = _least(path, value, pools, rule_pools, fb, aa, lambda s: s in ("feasible", "indeterminate"))
    return x_c, x_r


def aggregate(per_path):
    """per_path: list of (x_c, x_r). Returns the query-level result dict."""
    cs = [c for c, _ in per_path if c is not None]
    rs = [r for _, r in per_path if r is not None]
    if not rs:
        return {"result": "NO_AA_SUFFICES"}
    if cs and min(cs) == min(rs):
        return {"result": "PROVEN_MIN_AA", "min_aa": min(cs)}
    if cs:
        return {"result": "BOUNDS", "lower_bound": min(rs), "sufficient_upper_bound": min(cs)}
    return {"result": "INDETERMINATE", "lower_bound": min(rs)}
