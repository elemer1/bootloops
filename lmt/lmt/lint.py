"""Grounding gate: every rule's quote must be verbatim in the clause it cites, every
in-scope clause must be cited by some rule, and the rule file must name the
agreement whose excerpts it is checked against.

    python3 -m lmt.lint rules/jcrew2014.yaml      # exit 0 clean, 1 findings, 2 refused
"""
import sys

from .engine import load_rules, RuleError
from .source import anonymize, load, normalize


def lint(doc, src):
    findings = []
    if doc["agreement"] != src["agreement"]["id"]:
        return [f"FOREIGN: rule file is for {doc['agreement']!r}, excerpts are {src['agreement']['id']!r}"]
    clauses = {k: normalize(anonymize(v)) for k, v in src["clauses"].items()}
    defs = {f"def:{anonymize(k)}": normalize(anonymize(v)) for k, v in src["definitions"].items()}
    synth = {k: normalize(v) for k, v in (doc.get("synthetic_clauses") or {}).items()}
    cited = set()
    for r in doc["rules"]:
        c = r["cite"]
        key = c["clause"]
        text = clauses.get(key) or defs.get(key) or synth.get(key)
        if text is None:
            findings.append(f"{r['id']}: cites unknown clause {key!r}")
            continue
        q = normalize(anonymize(c["quote"]))
        if q not in text:
            findings.append(f"{r['id']}: quote not found verbatim in {key}: {c['quote'][:80]!r}")
            continue
        cited.add(key)
        for extra in r.get("also_cites") or []:
            cited.add(extra)
    missing = sorted(k for k in clauses if k not in cited)
    for k in missing:
        findings.append(f"COVERAGE: clause {k} is not cited by any rule")
    return findings


def coverage(doc, src):
    clauses = set(src["clauses"])
    cited = {r["cite"]["clause"] for r in doc["rules"]} | {x for r in doc["rules"] for x in r.get("also_cites") or []}
    return len(clauses & cited), len(clauses)


def main(argv):
    try:
        doc = load_rules(argv[0])
    except RuleError as e:
        print(f"REFUSED: {e}")
        return 2
    try:
        src = load(doc["agreement"])
    except FileNotFoundError:
        print(f"FOREIGN: no excerpt file for agreement {doc['agreement']!r}")
        return 1
    f = lint(doc, src)
    n, total = coverage(doc, src)
    for x in f:
        print(x)
    print(f"coverage {n}/{total}; {'CLEAN' if not f else f'{len(f)} finding(s)'}")
    return 0 if not f else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
