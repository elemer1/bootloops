# lmt — compute what a credit agreement lets you do

> Static covenant analysis tells you what a contract says. This computes what the
> contract lets you do.

**lmt compiles leveraged-loan covenants into a source-grounded, parameterized
transition system, and uses bounded search with an independent verifier to find or
rule out collateral-leakage paths.**

- *source-grounded*: every rule quotes its clause verbatim; the linter re-finds each
  quote in the pinned EDGAR text.
- *parameterized*: contested readings are named assumptions, and basket sizes are an
  explicit capacity ledger. Neither is hard-coded silently.
- *transition system*: entities, assets, liens and baskets change state step by step.
  It is not a checklist.
- *bounded*: every result is scoped to a stated model, entity universe and depth.
- *independently verified*: a second implementation re-derives every verdict.

Phase 0 is a backtest on the J.Crew 2014 term loan and the 2016 IP transfer:
**[CASE_JCREW.md](CASE_JCREW.md)**.

## Phase 0 result in one paragraph

Two blind encoders compiled the 92 in-scope clauses of the 2014 agreement. The
agreement was anonymized, and neither encoder was told the borrower or its history.
The two encodings permit the same first steps from every owner. Within depth 3, the
only route that moves the IP into an Unrestricted Subsidiary through an uncapped
basket is guarantor → non-guarantor restricted subsidiary (§7.02(c)(iv)+(n)) →
unrestricted subsidiary (§7.02(t)). That is the structure of the actual transaction.
The route exists only if an in-kind contribution counts as "proceeds" under §7.02(t)
(assumption A1). At the company's $250M valuation it fits the $277M of capacity; at
$347M it does not, unless a second contested reading (§7.02(i)) adds $75M. A real
post-J.Crew blocker (CPI Card Group, 2020) closes every path under every reading. A
blocker that binds only Loan Parties is bypassed through the non-guarantor subsidiary.
All 48 certificates pass the independent-verifier gate (identical path sets on both sides,
after the Phase 0.5 fixes described in the case report).

## Architecture: who is trusted with what

```
EDGAR text ──pin sha256──> clause excerpts (anonymized for encoders)
     │
     ├─ encoder A ─┐                         (LLM; translation only, under rules/SCHEMA.md)
     ├─ encoder B ─┴─> diff ─> adjudication ─> rules/jcrew2014.yaml
     │                                           │  lint: verbatim quotes, 100% coverage,
     │                                           │  cross-reference closure, lien release
     │                                           │  grounded in the Security Agreement
     ▼                                           ▼
scenario facts + capacity ledger ──> engine.py (BFS, booking choices, max-flow ledger)
                                                 │
                                                 ├─> certificate: WITNESS or BOUNDED_NON_REACHABILITY
                                                 └─> verify.py (separate code: DFS, Hall's condition) must agree
```

The search never invents a legal rule: every transition resolves to quoted source text.
That does **not** make the system error-free. The probability of a wrong conclusion is
the sum of compiler error, model incompleteness (scope, depth, entity universe) and
interpretation error, plus solver error. The last term is the one the verifier makes
small. The first three are what the controls (dual encoding, coverage, closure,
assumptions) target, and what a reader must still judge.

A certificate states: for this model (rules, assumptions, facts), this initial state,
this entity universe and depth k, no capacity-feasible path reaches the goal. It is a
**bounded reachability certificate**. It is not a proof that the contract is safe.

## What is new, and what is not

Treating contracts as state machines and model-checking them is not new. Examples:
Daskalopulu, *Model Checking Contractual Protocols* (JURIX 2000), with Petri nets; and
Hähnle, Laneve & Veschetti, *Formal Verification of Legal Contracts: A Translation-based
Approach* (iFM 2025), which verifies contracts already written in the Stipula
language. Commercial covenant tools are mature too. For example, 9fin publicly
describes AI covenant analysis with cited answers and covenant-capacity data.

What we have not found publicly offered, in a non-exhaustive search of commercial
product pages and the formal-contracts literature, is the combination: real, long, natural-language leveraged-finance agreements → an
LLM-assisted but source-grounded compilation with dual blind encoding → adversarial
bounded search for economically meaningful covenant paths, with capacity and contested
readings as explicit parameters → certificates re-derived by an independent checker.
The research problem is the compiler, not the solver.

LMT cases are the **benchmark**, not the market. If the pipeline handles J.Crew,
Serta, Chewy and Incora correctly, everyday covenant-capacity questions fall inside
its capability. See [VISION.md](VISION.md) for the product and commercial view.

## What this does not claim

- Literal text only: no prediction of how a court would rule (including the implied
  covenant of good faith and fair dealing); not legal advice.
- Results hold only within the declared scope. Notably, §7.08 (Transactions with
  Affiliates), which the J.Crew lenders alleged was breached, and §7.04 (mergers) are not
  modeled; see `out_of_scope` in the rule file.
- Phase 0 covers drop-downs. Uptier and priming cases (Serta, Incora, Boardriders) need
  debt classes, voting thresholds and amendment rights.
- One capacity input (the $27M Available Amount) is derived from a party's assertion,
  not verified.

## Layout

```
lmt/source.py    fetch + sha256 pin + clause/definition excerpts + anonymization
lmt/engine.py    rule loader, bounded search, booking choices, capacity classes
lmt/ledger.py    exact max-flow capacity ledger
lmt/verify.py    independent checker (no imports from engine/ledger)
lmt/lint.py      verbatim quotes, coverage, FOREIGN, multi-document release grounding
lmt/closure.py   cross-reference closure
lmt/certify.py   certificates per (assumption profile, asset value) + verifier cross-check
lmt/case.py      quick table of the backtest
lmt/tools.py     encoding diff, perturbation, overlays
rules/           SCHEMA.md, encodings A/B, adjudicated rules, scenario, blocker overlays
reports/         generated certificates
tests/           synthetic contract, regression counterexamples, J.Crew acceptance (42, ~45 s)
```

Run from `lmt/`: `python3 -m pytest tests -q`; `python3 -m lmt.certify --out reports`.
Re-fetch the source (network): `python3 -m lmt.source fetch && python3 -m lmt.source build`.
