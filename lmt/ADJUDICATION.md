# Adjudication record — J.Crew 2014 rule file

`rules/jcrew2014.yaml` is the rule file the case report uses. This file records how it
was produced from two independent encodings, and what was decided by hand.

## Process

1. The 92 in-scope clauses (§§6.11, 6.14, 7.01, 7.02, 7.05, 7.06, 9.11) and the 99
   definitions they reference were cut from the EDGAR filing (sha256 pinned in
   `lmt/source.py`) and anonymized: borrower, holding-company and brand names replaced.
2. Two encoders (separate sessions, no shared context) each received only
   `rules/SCHEMA.md` and the anonymized excerpts. They were told the study concerns
   "which intra-group asset transfers and subsidiary designations the covenants
   permit", were not told the borrower, its history, any transaction, or any target
   asset, and were instructed not to use outside knowledge or the web.
   Outputs: `rules/jcrew2014_A.yaml` (118 rules), `rules/jcrew2014_B.yaml` (119 rules).
   Both pass the linter: every quote verbatim, 92/92 clauses covered.
3. Diff (`lmt/tools.py`):
   - structural: 24 of 92 clauses encoded differently;
   - behavioral: **0 disagreements** in which first steps are permitted, from every
     possible owner of the asset; identical sets of leakage shapes and capacity classes
     at depth 3 (`tests/test_jcrew.py::test_blind_encodings_*`).
4. Base chosen: encoder B (more complete lien-attachment and release effects).
   Disputed readings became **named assumptions** rather than being resolved silently.

## The three interpretation assumptions

Both encoders independently flagged these clauses as ambiguous.

| id | clause | question | encoded as |
|---|---|---|---|
| A1 | 7.02(t) | Is an onward Investment of *property* (here IP) that a non-Loan-Party Restricted Subsidiary itself received in kind under 7.02(c)(iv), (i)(B) or (n) "financed with the proceeds received" from that Investment? | 7.02(t) active only when A1 is on |
| A2 | 7.02(i) | Is an intra-group contribution to a wholly owned Restricted Subsidiary a "purchase or other acquisition" (a Permitted Acquisition)? | all 7.02(i) rules active only when A2 is on |
| A3 | 7.02(c)(ii)/(iii) | "Non-Loan Party" means any Subsidiary that is not a Loan Party. Does that include Unrestricted Subsidiaries as the investing party? | the Unrestricted-Subsidiary actor split into a separate rule active only when A3 is on |

A1 is the reading the historical path depends on (see CASE_JCREW.md). We found no
court ruling on it. What we verified: Amendment No. 1 (July 13, 2017; EDGAR EX-10.1)
defines the 2016 IP transfers and lien releases as "Specified Liability Management
Transactions" and leaves the text of 7.02(t) unchanged.

## Structural differences judged cosmetic (no behavioral effect in this scope)

- `counterparty: [any]` (B) vs. an explicit role list (A); `forms` omitted (B) vs.
  listed (A).
- Clause splits with different ids (e.g. A `7.02(i)` vs. B `7.02(i).lp/.nlp/.nlp_actor`;
  A `7.05(d)`/`7.05(d)(i)` vs. B `7.05(d).nlp`).
- A encodes 6.11, 6.11(b), 7.05(a), 7.05(b) as `na`; B encodes attach-lien effects and
  sale-only exceptions. Sale-only exceptions cannot produce leakage (sales are
  reported separately), and the engine re-attaches the lien to any Loan Party asset.
- 7.02(s)/7.05(s) asset scope (A `any`, B `other`): switched off for this scenario by
  the fact "no securitization financing" (`rules/scenario_jcrew2016.yaml`).
- 7.06(l) asset scope (A `any`, B `cash` for limb (x)): only reachable through dividends,
  whose onward paths are capacity-infeasible in every profile.

## Edits by the adjudicator after the encoders finished

- A1/A2/A3 tags (above).
- Lien release: 9.11(a)(ii), 9.11(a)(iv) and 9.11(c) now also cite the Term Loan
  Security Agreement §7.12(b) (EDGAR, sha256 pinned in the rule file), which releases
  the security interest "in the circumstances set forth in Section 9.11(a)". The linter
  requires this second grounding for every 9.11 release rule.
- `out_of_scope`: every section referenced from inside the scope but not encoded is
  declared with a treatment (`python3 -m lmt.closure rules/jcrew2014.yaml`). The material
  gap is **§7.08 (Transactions with Affiliates)**, which the lenders' complaint alleged
  was breached; it is not modeled in Phase 0.

## Disclosure

The adjudicator (the same model family as the encoders, in the coordinating session)
knew the J.Crew case and its outcome. The encoders' outputs agreed behaviorally before
any adjudication, and every adjudication edit is listed above, but the
adjudication step is not blind.
