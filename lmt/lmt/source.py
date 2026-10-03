"""Fetch a credit agreement from EDGAR, pin its sha256, and cut it into clause excerpts.

The excerpt file is the only text the encoders and the linter see. Every rule's
`cite.quote` must be found verbatim (after `normalize`) inside the clause it names.

    python3 -m lmt.source fetch   # download + pin (needs network)
    python3 -m lmt.source build   # raw html -> source/jcrew2014.json
"""
import hashlib
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source"

AGREEMENT = {
    "id": "jcrew2014",
    "title": "Amended and Restated Credit Agreement dated as of March 5, 2014 (term loan)",
    "url": "https://www.sec.gov/Archives/edgar/data/1051251/000156459014000667/jcg-ex10_201403057.htm",
    "raw_sha256": "b1a2f775b8af8ef62e651fce82ada90a7f1c323228584be50cd7ca9c837d9113",
    # Phase 0 scope: the five covenant families plus designation and release.
    "scope_sections": ["6.11", "6.14", "7.01", "7.02", "7.05", "7.06", "9.11"],
}

# Names that identify the borrower group. Encoders see the anonymized text only;
# the linter applies the same table, so quotes stay verbatim against it.
ANONYMIZE = [
    ("J. Crew Group, Inc.", "BorrowerCo, Inc."),
    ("J. Crew", "BorrowerCo"),
    ("J.Crew", "BorrowerCo"),
    ("Chinos Intermediate Holdings B, Inc.", "HoldCo B, Inc."),
    ("Chinos", "HoldCo"),
    ("Madewell", "BrandTwo"),
]

UA = "lmt-research (covenant reachability study) research@example.org"


def raw_path():
    return SRC / f"{AGREEMENT['id']}.raw.htm"


def fetch():
    req = urllib.request.Request(AGREEMENT["url"], headers={"User-Agent": UA})
    data = urllib.request.urlopen(req, timeout=60).read()
    got = hashlib.sha256(data).hexdigest()
    if got != AGREEMENT["raw_sha256"]:
        raise SystemExit(f"sha256 mismatch: got {got}, pinned {AGREEMENT['raw_sha256']}")
    raw_path().write_bytes(data)
    print(f"ok {len(data)} bytes {got}")


def normalize(s):
    """Whitespace- and quote-insensitive form used for verbatim matching."""
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", s).strip()


def anonymize(s):
    for a, b in ANONYMIZE:
        s = s.replace(a, b)
    return s


def html_to_lines(raw):
    t = raw.decode("latin-1")
    t = re.sub(r"(?is)<(p|div|br|tr)[^>]*>", "\n", t)
    t = re.sub(r"(?s)<[^>]+>", "", t)
    t = html.unescape(t).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    lines = [l.strip() for l in t.split("\n")]
    # drop blank lines and bare page numbers
    return [l for l in lines if l and not re.fullmatch(r"[ivxlc\d]+", l)]


def body_sections(lines):
    """SECTION n.nn headings in the body (the second ARTICLE I onward)."""
    starts = [i for i, l in enumerate(lines) if l == "ARTICLE I"]
    lo = starts[1]
    hi = next(i for i in range(lo, len(lines)) if lines[i].startswith("EXHIBIT A"))
    body = lines[lo:hi]
    idx = [i for i, l in enumerate(body) if re.match(r"^SECTION \d+\.\d+\.", l)]
    out = {}
    for a, b in zip(idx, idx[1:] + [len(body)]):
        sec = re.match(r"^SECTION (\d+\.\d+)\.", body[a]).group(1)
        out[sec] = [l for l in body[a:b] if not l.startswith("ARTICLE ")]
    return out


LETTERS = "abcdefghijklmnopqrstuvwxyz"


def split_clauses(sec, lines):
    """Top-level (a), (b), ... clauses. (i) is a letter only when 'i' is the next letter due."""
    out = {sec: lines[0]}
    cur, nxt = sec, 0
    for l in lines[1:]:
        m = re.match(r"^\(([a-z]{1,2})\)", l)
        if m and nxt < len(LETTERS) and m.group(1) == LETTERS[nxt]:
            cur = f"{sec}({m.group(1)})"
            out[cur] = l
            nxt += 1
        elif m and m.group(1) == LETTERS[nxt - 1] * 2 if nxt else False:
            cur = f"{sec}({m.group(1)})"
            out[cur] = l
        else:
            out[cur] += "\n" + l
    return out


def definitions(lines):
    defs, cur = {}, None
    for l in lines[1:]:
        m = re.match(r"^“([^”]+)”", l)
        if m:
            cur = m.group(1)
            defs[cur] = l
        elif cur:
            defs[cur] += "\n" + l
    return defs


def build():
    raw = raw_path().read_bytes()
    if hashlib.sha256(raw).hexdigest() != AGREEMENT["raw_sha256"]:
        raise SystemExit("raw file does not match pinned sha256; run fetch")
    secs = body_sections(html_to_lines(raw))
    clauses = {}
    for s in AGREEMENT["scope_sections"]:
        clauses.update(split_clauses(s, secs[s]))
    defs = definitions(secs["1.01"])
    scope_text = "\n".join(clauses.values())
    used = sorted(t for t in defs if re.search(r"\b" + re.escape(t) + r"\b", scope_text))
    doc = {
        "agreement": {k: AGREEMENT[k] for k in ("id", "title", "url", "raw_sha256", "scope_sections")},
        "anonymize": ANONYMIZE,
        "clauses": clauses,
        "definitions": {t: defs[t] for t in used},
    }
    out = SRC / f"{AGREEMENT['id']}.json"
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    print(f"{len(clauses)} clauses, {len(used)} definitions -> {out}")


def load(agreement_id="jcrew2014"):
    return json.loads((SRC / f"{agreement_id}.json").read_text())


if __name__ == "__main__":
    {"fetch": fetch, "build": build}[sys.argv[1]]()
