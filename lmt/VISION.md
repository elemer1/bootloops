# Vision — product, benchmark, and where this goes

This file holds the commercial and strategic view, kept out of the README on purpose.
Probabilities here are the author's subjective estimates with no calibrated base rate.

## The abstraction

A credit agreement is a natural-language program that governs how value may move
between parties. Most tools turn the document into information (terms, tags,
capacity numbers). This project turns it into an executable environment and asks
which future capital structures are reachable from today's.

    document → executable environment → reachable worlds

## Three artifacts

1. **Engine.** Text → rules → state graph → bounded search → certificate checked by
   an independent verifier.
2. **Benchmark (ContractSecBench).** Historical LMT cases, each with original
   agreements, amendments, the historical state, the known transaction, court filings,
   the disputed readings, a machine-readable path and counterfactual blockers. Metrics:
   exploit recall, false-path rate, citation accuracy, rule coverage, agreement between
   independent compilers, and whether blocker overlays flip the right verdicts.
   This is the hardest asset to copy and the only way to know whether the compiler is
   any good.
3. **Reports.** Human-readable path reports: each step, its clauses, its capacity
   draw, the assumptions it needs, the blocker that would close it, and the
   machine certificate.

Moat order: benchmark → compiler → ontology → trust → distribution. The ontology
(the minimal set of primitives that 30+ real structures force on the schema:
entities, assets, liens, baskets, then debt classes, voting rights, sacred rights,
amendments, guarantor status, automatic release, exchanges…) is the real "DSL moat".
It comes from working through hard cases, not from the schema file.

## Product wedge

Not "find a $1bn exploit in 10 minutes". The first product is a **covenant
attack-surface map**. For each of debt, liens, investments, restricted payments,
asset sales, unrestricted-subsidiary routes, non-guarantor leakage, collateral release
and amendment surfaces, it shows the current capacity, the reachable transactions, the
assumptions they need, and the source clauses. Lawyers still make the call; the engine
enumerates and certifies.

Development likely runs: human-led and machine-assisted audits → machine-led audits
with human sign-off → self-serve scans that hand `INTERPRETATION_REQUIRED` nodes to
counsel. Services early on are fine; they are how the benchmark grows.

## Value (subjective estimates)

- Professional capital and credibility in restructuring, special situations, private
  credit and leveraged finance, from a reproducible, certified case study: ~50%.
- Partnership with, or acquisition by, a covenant-data vendor: ~15%.
- Pre-closing document-defense work for direct lenders and their counsel: ~15%.
- Research: a prospective test (do paths flagged today get used later?) is the
  publishable core.

## Roadmap

- **Phase 1:**
  - encode §7.08 (affiliate transactions) and §7.04 (mergers) through the same blind
    dual-encoding protocol, and re-run J.Crew;
  - replace the derived Available Amount with a computed one;
  - add a second drop-down case (e.g. Chewy/PetSmart) and the first uptier case
    (Serta), which forces debt classes and voting.
- **Phase 2 (forward test):** freeze the compiler, schema and search; run on current
  agreements with no LMT yet; hash and timestamp the reports; check outcomes later,
  and have practitioners blind-review whether each path is executable.
- **Other jurisdictions:** the method carries over; the ontology does not.
  - Hong Kong adds registration and perfection (Companies Ordinance Part 8 charge
    filings are public records).
  - The PRC adds statutory priority and registration rules (e.g. Civil Code Art. 416
    purchase-money priority) and regulatory discretion (SAFE cross-border guarantee
    registration). Results there need a richer verdict scale: unconditional,
    assumption-dependent, interpretation required, outside the deterministic model
    (regulatory or judicial discretion), and bounded-unreachable.
  - Start where verification stays cheap: registry-versus-instrument consistency in
    Hong Kong, before offshore keepwell structures.

## Fundraising note

Reviewers pointed to accelerator-backed companies in AI × commercial lending and private
credit (not independently checked here), so a category mismatch is unlikely. What will matter is the artifact: a reproducible case report
with certificates and an independent verifier, plus two or three design partners.
