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
    synth.update({k: normalize(v["text"]) for k, v in (doc.get("external_clauses") or {}).items()})
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
        for c2 in r.get("cites") or []:
            t2 = clauses.get(c2["clause"]) or defs.get(c2["clause"]) or synth.get(c2["clause"])
            if t2 is None or normalize(anonymize(c2["quote"])) not in t2:
                findings.append(f"{r['id']}: secondary cite not found verbatim in {c2['clause']}")
    # multi-document grounding: a lien release must also be grounded in the security document
    for prefix, doc_prefix in (doc.get("release_requires") or {}).items():
        for r in doc["rules"]:
            if r["kind"] == "effect" and r.get("then") == "release_lien" and r["cite"]["clause"].startswith(prefix):
                if not any(c["clause"].startswith(doc_prefix) for c in r.get("cites") or []):
                    findings.append(f"{r['id']}: lien release not grounded in a {doc_prefix}* security-document clause")
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
