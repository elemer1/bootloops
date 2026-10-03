# lmt — covenant reachability search for credit agreements

**Question this project answers:** given the covenants of a leveraged credit agreement,
*does a sequence of individually permitted steps exist that moves a collateral asset out
of the lenders' reach?* If yes, the search returns the path, every step cited to the
agreement's own words. If no, it returns a certificate: within a declared bound, no such
path exists, and for every attempted step, the clause that blocks it.

Phase 0 is a backtest on one public case: the J.Crew Group term loan agreement of
March 5, 2014 (filed on EDGAR) and the 2016 transfer of intellectual property to an
unrestricted subsidiary that later gave the "J.Crew blocker" its name.

## Why this problem

**A credit agreement is a rule system written in English.** The negative covenants
(liens, investments, indebtedness, dispositions, restricted payments), the definitions,
and the designation and release mechanics each carve out exceptions, and the exceptions
cross-reference one another. A liability-management "drop-down" is not an arithmetic
error. It is a reachability property of that rule system: several baskets, each
permitted on its own terms, chain into a path from a guarantor to an entity outside the
covenant net. Lawyers draft clause by clause from precedent; nobody enumerates the
combinations. Enumerating combinations is what a deterministic search does well.

**Where existing tools sit.** Document analytics in this market mostly does one of two
things: semantic extraction and tagging ("does this deal have a J.Crew blocker?"), or
cash-flow arithmetic on numbers that already happened. Covenant-analysis vendors (Octus,
9fin, CreditSights) sell expert and AI-assisted reviews against known loophole patterns,
which shows the market pays for this work. Octus, for example, reported that about 71% of
J.Crew blockers in 2025 European high-yield bonds had material loopholes. What this
project adds:

1. a search for paths nobody has named yet, not only a check against known patterns;
2. a bounded proof of absence ("within these entities and k steps, no path exists"),
   which tests whether a blocker actually blocks rather than whether one is present;
3. every step tied to verbatim contract text, so a lawyer can audit it line by line.

**Why it fits a machine-checked method.** The approach borrows from BootLoops (a harness
for LLM-driven precision science): only take problems whose answers can be checked
independently, and build the checks before trusting the answers. Here a found path can
be audited step by step, and historical LMT transactions are an external ground truth to
backtest against.

## Design: separate the translator from the solver

- **An LLM is used only as a translator** from clause text to rules, under a schema
  ([rules/SCHEMA.md](rules/SCHEMA.md)). Every rule must quote its clause verbatim; the
  linter re-finds each quote and refuses a rule file that leaves any in-scope clause
  uncited.
- **The search is plain deterministic code** ([lmt/engine.py](lmt/engine.py)):
  breadth-first enumeration of transfers and designations up to a depth bound. It never
  reads the agreement and never calls a model.
- Translation errors are still possible. The controls below are there to catch them; they
  do not make errors impossible.

## Controls against a known answer leaking in

J.Crew is famous, and a language model may already know the answer. The contamination
risk is in the encoding step: an encoder could, knowingly or not, translate only the
clauses that matter for the known path. Mitigations:

1. **Deterministic search.** The model never reasons about paths.
2. **Uniform coverage.** Every clause of the in-scope sections must be encoded; the
   linter fails on any gap.
3. **Two blind, independent encodings.** Two isolated sessions encode an anonymized copy
   of the text (borrower and brand names removed), told nothing about the borrower's
   history. Their outputs are diffed clause by clause and each difference is adjudicated
   against the text.
4. **Perturbation invariance.** Rule ids, entity names and rule order are randomized and
   the search is re-run; the set of paths must not change.

Residual risk is stated in the case report. The clean test is forward: flag paths in
agreements today and check later whether they get used.

## Test matrix

| test | rules | expected |
|---|---|---|
| T1 recover known path | 2014 rules as encoded | path found: guarantor → non-guarantor restricted subsidiary → unrestricted subsidiary |
| T2 blocker | + standard J.Crew-style blocker (synthetic overlay) | unreachable within bound, with certificate |
| T3 remove springboard | − the non-guarantor springboard exception | unreachable within bound |
| T4 grounding | rules vs EDGAR text | every quote found verbatim; 100% clause coverage |
| T5 foreign | rules checked against another agreement | fails by name |
| T6 perturbation | randomized names and order | T1–T3 results unchanged |

## What this does not claim

- It answers only whether the **literal text** permits a path. It does not predict how a
  New York court would rule (including on the implied covenant of good faith and fair
  dealing), and it is not legal advice.
- Certificates hold **only within the stated bound**: the entity universe, the depth, and
  the covenant sections in scope. Covenants outside Phase 0 scope (for example
  transactions with affiliates, fundamental changes) are not modeled.
- Phase 0 checks **structure, not amounts**. Size-limited baskets are assumed to have
  room, and every path lists those assumptions. Whether the baskets were large enough is
  Phase 1.
- Phase 0 covers drop-downs only. Uptier and priming transactions (Serta, Incora,
  Boardriders type) need voting-threshold and amendment modeling, which is later work.
- No dollar amounts or deal-team attributions are reported unless verified.

## Where the value is

- **Personal and professional capital.** A reproducible case — recover the J.Crew path
  blind, then certify that a blocker closes it — demonstrates a combination that is rare:
  credit documentation, capital-structure conflict, and formal computation.
- **Document defense for lenders.** Direct lenders and private-credit funds draft their
  own agreements and fear LMTs. A pre-closing check of the form "these collateral assets
  cannot be moved out under these covenants, within this bound" is a concrete product.
- **Analysis for distressed and special-situations investors.** A sandbox to map a
  capital structure's attack surface before a lawyer's memo.
- **A capability layer** for data vendors, as an engine behind their covenant research.
- **Research.** A falsifiable forward test: do paths flagged today predict the LMTs that
  happen later?

**What carries over to other fields.** The template is: contract or statute → executable
rules with verbatim provenance → backtest against historical events → adversarial
search with a bounded completeness certificate → forward prediction as the falsification
test. Candidates: tax rules (Pillar Two structuring paths), insurance and reinsurance
trigger chains, ISDA termination events, borrowing-base rules in asset-based finance.

## Layout

```
lmt/source.py     fetch + sha256 pin + clause/definition excerpts (source/jcrew2014.json)
lmt/engine.py     rule loader/validator and bounded reachability search
lmt/lint.py       verbatim-quote and coverage gate; FOREIGN check
lmt/tools.py      encoding diff, perturbation, overlays
rules/            SCHEMA.md, encodings, synthetic blocker overlays
tests/            synthetic contract tests + J.Crew acceptance tests
CASE_JCREW.md     the backtest report
```

Run: `python3 -m pytest tests -q` (from `lmt/`). Re-fetch the source:
`python3 -m lmt.source fetch && python3 -m lmt.source build`.
