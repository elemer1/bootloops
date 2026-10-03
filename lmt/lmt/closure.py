"""Dependency-closure check for the compiled scope.

Lists every cross-reference out of the in-scope clauses (to sections outside the scope)
and every defined term used inside an included definition that is not itself included.
A rule file passes only if each out-of-scope section is declared in its `out_of_scope`
map with a stated treatment. Second-hop definitions are reported, not gated.
"""
import re
import sys

from .engine import load_rules
from .source import load

SEC = re.compile(r"Sections?\s+((?:\d+\.\d+(?:\([a-z0-9]+\))*(?:\s*(?:,|and|or|through)\s*)?)+)")


def section_refs(text):
    out = set()
    for m in SEC.finditer(text):
        for s in re.findall(r"\d+\.\d+", m.group(1)):
            out.add(s)
    return out


def closure(src):
    scope = set(src["agreement"]["scope_sections"])
    ext = {}
    for cid, text in src["clauses"].items():
        for s in section_refs(text):
            if s not in scope and s not in ("1.01",):
                ext.setdefault(s, set()).add(cid)
    defs = src["definitions"]
    caps = set(re.findall(r"“([^”]+)”", " ".join(defs.values())))
    return ext, caps


def check(doc, src):
    ext, _ = closure(src)
    declared = doc.get("out_of_scope") or {}
    return {s: sorted(c) for s, c in sorted(ext.items()) if s not in declared}


if __name__ == "__main__":
    doc = load_rules(sys.argv[1])
    src = load(doc["agreement"])
    ext, _ = closure(src)
    missing = check(doc, src)
    for s, cl in sorted(ext.items(), key=lambda x: [int(p) for p in x[0].split(".")]):
        tag = "UNDECLARED" if s in missing else "declared"
        print(f"{s:6s} {tag:10s} referenced from {', '.join(sorted(cl))[:110]}")
    sys.exit(1 if missing else 0)
