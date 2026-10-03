# Case report — J.Crew 2014 term loan, 2016 IP transfer (Phase 0 backtest)

## Question

Given only the 2014 credit agreement's covenant text and the facts as of late 2016,
does the model recover a **candidate** path — every transition grounded in quoted text,
every basket within its capacity — that has the structure of the transfer J.Crew
actually made? And does a real blocker close it?

Whether the 2016 transfer was legally permitted was never decided on the merits. This
report does not say it was. It says which paths the text admits, under which stated
readings.

## Answer key (verified, with sources)

From the lenders' complaint, *Eaton Vance Mgmt. et al. v. J. Crew Group, Inc. et al.*,
N.Y. Sup. Ct. Index No. 654397/2017 (filed 2017-06-22), paras. 58-60, 82-84:

- A 72.04% undivided interest in the trademark collateral moved from J. Crew
  International (a Loan Party) to J. Crew International Cayman Limited (a Restricted
  Subsidiary that, being foreign, is not a Loan Party), then through a chain of
  Unrestricted Subsidiaries, each step "a contribution to equity capital of the
  transferee".
- The company asserted capacity of about $277M under §7.02(c)(iv) and (n), and certified
  the transferred interest at $250M (72.04% of a $347M valuation of the whole).
- The lenders argued the value could be as high as $347M, above the asserted capacity.

Other inputs: Total Assets of $1,499.3M at 2016-10-29 (10-Q, SEC XBRL), so the dollar
floors of the percentage baskets govern; the Term Loan Security Agreement (2011, EDGAR)
§7.12(b) for lien release.

## Model and bound

- Rules: `rules/jcrew2014.yaml` (121 rules over 92 clauses; how it was produced:
  [ADJUDICATION.md](ADJUDICATION.md)).
- Entity universe: Holdings, Borrower, a Guarantor holding the IP, a domestic and a
  foreign non-Loan-Party Restricted Subsidiary, an Unrestricted Subsidiary.
- Actions: transfers (contribution, dividend, sale) and designations; depth ≤ 3.
- Goal: IP owned by an Unrestricted Subsidiary, lenders' lien released, no fair-value
  sale on the path.
- Capacity ledger: §7.02(c)(iv) $150M, §7.02(n) $100M, §7.02(i)(B) $75M floors; a
  shared Available Amount pool of $27M **derived** from the company's asserted $277M
  (not independently verified).
- Interpretation assumptions A1 (7.02(t) "proceeds"), A2 (7.02(i) intra-group
  acquisitions), A3 ("Non-Loan Party" includes Unrestricted Subsidiaries); all 8
  combinations are run.

## Results

48 certificates (`reports/`), each cross-checked by an independent implementation
(`lmt/verify.py`: depth-first enumeration with no pruning, Hall's condition instead of
max-flow). **The verifier agrees on all 48.**

**Base agreement, $250M (company's value):**

| assumptions on | verdict |
|---|---|
| none, A2, A3, A2+A3 | bounded non-reachability |
| A1, A1+A3 | witness: guarantor → non-guarantor RS → unrestricted |
| A1+A2, A1+A2+A3 | witness (same shape; more ways to book step 1) |

**Base agreement, $347M (whole trademark value):** reachable only under A1+A2. Under
A1 alone, $277M of capacity cannot carry $347M, which mirrors the lenders' argument.
With A2, the §7.02(i)(B) basket adds $75M ($352M total). The complaint does not
mention §7.02(i), so this is a route the model surfaced under a contested reading.

**Witness (A1, $250M):**

1. Guarantor → non-Loan-Party Restricted Subsidiary, contribution.
   - Investments: booked under §7.02(c)(iv) ("by any Loan Party in any Non-Loan Party that is a Restricted Subsidiary") and §7.02(n), within $277M.
   - Dispositions: §7.05(e) ("Dispositions permitted by Sections 7.02 (other than Section 7.02(e))").
   - Lien released: §7.05 ("such Collateral shall be sold free and clear of the Liens created by the Loan Documents") and §9.11(a)(ii) ("transfer permitted hereunder … to any Person other than Holdings, the Borrower or any of its Domestic Subsidiaries that are Guarantors"), which reaches the Security Agreement via §7.12(b).
2. Non-Loan-Party Restricted Subsidiary → Unrestricted Subsidiary, contribution.
   - Investments: §7.02(t) ("Investments made by any Restricted Subsidiary that is not a Loan Party to the extent such Investments are financed with the proceeds received by such Restricted Subsidiary from an Investment in such Restricted Subsidiary made pursuant to Sections 7.02(c)(iv), (i)(B) or (n)"), uncapped, under A1.

This has the structure of the historical step 1 → step 2. It is the **only**
route into an Unrestricted Subsidiary through an uncapped basket. Every other
structural route ends in a capped basket that cannot carry $250M.

**Blockers:**

- **Real** blocker language from CPI Card Group's 2020 Super Senior Credit Agreement
  (EDGAR), §6.03(e) (no transfer of Material IP, "whether through an in-kind Investment
  or Restricted Payment … to any other Person other than the Borrower or a Subsidiary
  Loan Party") and §5.13(iv) (no designation of an IP-owning subsidiary), grafted onto
  the J.Crew rules as a counterfactual: **no structural path under any profile**.
- **Deliberately weak** synthetic blocker (binds only Loan Parties, only transfers into
  Unrestricted Subsidiaries): the search finds the **bypass**. The guarantor moves the IP to
  a non-guarantor restricted subsidiary, which the blocker does not bind, and that
  subsidiary moves it on.
- Removing §7.02(t) (T3): no feasible $250M path under any profile.

**Both blind encodings** give identical first-step permissions from every owner and
identical leakage shapes and capacity classes, before any adjudication.

## What this shows and what it does not

Shows, within the stated model:
- the historical structure is the unique uncapped route out of the collateral;
- that route stands or falls with one interpretive question (A1), which the model
  isolates;
- capacity is decisive. At the company's $250M figure the path fits; at $347M it fits
  only under a second contested reading.

Does not show:
- that the transfer was lawful;
- anything about covenants outside scope. **§7.08 (Transactions with Affiliates)**, which
  the lenders alleged was breached, is not modeled, nor are mergers (§7.04).
- anything beyond depth 3 and the six-entity universe.

The witness books step 1 through the non-guarantor restricted subsidiary as a
*domestic* or *foreign* entity; the model does not require the Cayman route that was
actually used.

## Contamination controls and residual risk

- Deterministic search and an independent verifier; neither reads the agreement.
- Uniform coverage: 92/92 clauses encoded by both encoders; closure check over
  cross-references.
- Two blind, anonymized encodings; behaviorally identical before adjudication.
- Perturbation invariance (renamed rules and entities, shuffled order).
- Residual: the encoders are language models that may recognize the agreement's
  structure despite anonymization; the adjudicator knew the case; the schema's
  vocabulary (e.g. `funded_by`) was designed by someone aware of LMT patterns. The clean
  test is prospective: freeze the pipeline, run it on agreements with no LMT yet, and
  check later.

## Reproduce

```
cd lmt
python3 -m pytest tests -q                  # 30 tests, ~15 s
python3 -m lmt.lint rules/jcrew2014.yaml    # grounding + coverage
python3 -m lmt.closure rules/jcrew2014.yaml # cross-reference closure
python3 -m lmt.certify --out reports        # 48 certificates + verifier cross-check, ~1 min
```
