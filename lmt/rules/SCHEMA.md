# Rule schema (v1) — how a covenant clause becomes a rule

This file is the whole contract an encoder works from. The encoder sees only this
file and the clause excerpts in `source/<agreement>.json` (anonymized). The search
engine (`lmt/search.py`) is deterministic code; it never reads the agreement, only
the rules.

## The modeled world (fixed vocabulary)

**Roles** (an entity has exactly one):

| role | meaning |
|---|---|
| `holdings` | the parent guarantor above the Borrower ("Holdings") |
| `borrower` | the Borrower |
| `guarantor` | a Restricted Subsidiary that is a Loan Party (Guarantor) |
| `nlp_rs` | a Restricted Subsidiary that is **not** a Loan Party (domestic or foreign) |
| `unrestricted` | an Unrestricted Subsidiary |

`loan_party` = holdings, borrower, guarantor. `restricted_subsidiary` = guarantor, nlp_rs.
Entities may also carry `foreign: true|false`.

**Asset types:** `ip` (intellectual property), `cash`, `equity` (equity interests in a
subsidiary), `other`. Patterns may use `any`.

**Actions** the engine can attempt:

| action | fields | example |
|---|---|---|
| `transfer` | `src`, `dst`, `asset`, `form` | a Guarantor contributes IP to a subsidiary |
| `designate` | `entity` | the board designates a Restricted Subsidiary as Unrestricted |

`form` of a transfer: `contribution` (to a subsidiary, as equity/capital — no
consideration back), `dividend` (to a parent, no consideration back), `sale`
(for fair-market-value consideration), `license` (non-exclusive or exclusive license).

## Rule kinds

Every rule has `id` (unique), `kind`, and `cite`. `cite` = `{clause: <clause id from the
excerpt file, or "def:<Defined Term>">, quote: "<verbatim text>"}`. The quote must
appear verbatim (whitespace and curly quotes normalized) inside that clause. Keep
quotes short: the operative words that justify the rule, not the whole clause.

### 1. `characterization` — which restrictions an action triggers

```yaml
- id: char.contribution
  kind: characterization
  action: transfer          # transfer | designate
  forms: [contribution]     # transfer only
  triggers: [investments, dispositions]   # restriction categories
  cite: {clause: "def:Investment", quote: "..."}
```

Restriction categories: `investments`, `dispositions`, `restricted_payments`,
`liens`, `designation`. An action must be permitted under **every** category it
triggers.

### 2. `exception` — a permission inside a restriction

```yaml
- id: "7.02(x)"
  kind: exception
  category: investments
  action: transfer               # or designate
  actor: [guarantor, borrower]   # roles of the entity making the investment/disposition/payment
  counterparty: [nlp_rs]         # roles of the recipient (for designate: the entity designated)
  assets: [any]                  # asset types; transfer only
  forms: [contribution, sale]    # transfer only; omit = any form
  foreign: any                   # counterparty foreign status: true | false | any
  capacity: capped               # unlimited | capped
  capacity_note: "greater of $X and Y% of Total Assets"   # verbatim-ish, for humans
  conditions: ["no Event of Default"]   # symbolic conditions assumed satisfiable; listed in output
  funded_by: ["7.02(y)"]         # optional: only if the actor received the asset via a transfer
                                 # permitted under one of these rule ids
  via: null                      # optional cross-reference, see below
  cite: {clause: "7.02(x)", quote: "..."}
```

**Cross-references** ("Dispositions permitted by Section 7.02"): use
`via: {category: investments, except: ["7.02(e)"]}`. The action is then permitted
in this category if it is permitted under `investments` using any rule except those
listed. The engine guards against circular references.

### 3. `prohibition` — an override that forbids a matching action whatever the exceptions say

```yaml
- id: "X.notwithstanding"
  kind: prohibition
  action: transfer
  actor: [any]
  counterparty: [unrestricted]
  assets: [ip]
  cite: {...}
```

### 4. `designation` — conditions to designate an entity (use `kind: exception`, `category: designation`, `action: designate`)

If the agreement deems a designation to be an Investment, also add a
`characterization` rule with `action: designate` and `triggers: [designation, investments]`.

### 5. `effect` — what happens to the lenders' lien

```yaml
- id: "9.11(a).transfer"
  kind: effect
  on: transfer                # transfer | designate
  when: {counterparty: [nlp_rs, unrestricted]}   # roles after the action
  then: release_lien          # release_lien | attach_lien
  cite: {...}
```

If no `release_lien` effect matches, an encumbered asset stays encumbered after the
action. An asset owned by a Loan Party starts encumbered.

### 6. `na` — the clause does not bear on the modeled actions

```yaml
- id: "7.01(c)"
  kind: na
  reason: "tax liens; no inter-entity asset movement"
  cite: {clause: "7.01(c)", quote: "Liens for taxes"}
```

## Coverage rule

**Every clause id in the excerpt file's scope must be cited by at least one rule**
(an exception, prohibition, effect, characterization or `na`). Do not skip clauses
and do not pick only the ones that look relevant. When unsure, encode it as an
exception with conservative fields and add a `note:`.

## What not to do

- Do not use knowledge of this borrower, its history, or any transaction it did.
- Do not invent numbers or conditions that are not in the quoted text.
- Do not decide amounts. Mark size-limited baskets `capacity: capped` and quote the cap.

## Engine-side extensions (not used by encoders)

- `owns_tracked_asset: true` on a `designate` prohibition: applies only when the entity being
  designated owns the tracked asset. Used by the synthetic blocker overlays in `rules/overlay_*.yaml`.
- `synthetic_clauses:` in an overlay file: text written by us (never from the agreement), cited as
  `SYN.*`, so the linter still checks that each overlay rule quotes its own text verbatim.
- `assumption: Ak` on any rule: the rule is active only when interpretation assumption Ak is
  switched on; the rule file's `assumptions:` map states each one in words. Results are reported
  per combination of assumptions.
- `cites: [{clause, quote}]`: additional grounding in another clause or document
  (`external_clauses:` holds pinned text from other filings). `release_requires` makes the
  linter demand such a second grounding for lien releases.
- `out_of_scope: {section: treatment}`: every section referenced from inside the scope but not
  encoded, with how it is treated (`python3 -m lmt.closure`).
- Booking: when several investment baskets permit a step, the engine branches over how the step
  is booked (a set of capped baskets sharing the value, or one uncapped basket). The booking
  decides capacity use and which `funded_by` conditions later steps can meet.

## Search and ledger semantics (Phase 0.5)

- **Reference mode:** every action sequence up to the depth bound is enumerated, with no
  cross-path deduplication and no removal of repeated states. The only early stop: a path is not
  extended once it reaches the goal. `verify.py` applies the same rule.
- **`funded_by`:** checked against the transfer that brought the asset to its current holder
  (designations in between do not break the link). That transfer's booking must be a non-empty
  subset of the listed rules. Whole-asset moves only: partial transfers, mixed-source splitting and
  source reallocation are not supported.
- **Ledger:** step → per-step rule node → shared pool. Eligibility is enforced on rule nodes.
  The confirmed model proves feasibility; the relaxed model (each unpriced capped rule gets its own
  pool bounded by value × capped steps) is used only to rule out. Per path: feasible /
  indeterminate / infeasible. Per query: CANDIDATE_PATH / INDETERMINATE / BOUNDED_NON_REACHABILITY,
  or VERIFICATION_FAILED if engine and verifier disagree.
- **Designations** are deemed Investments at the designated entity's fair market value: the
  asset's value if it holds the tracked asset, otherwise unknown.
- **Capacity input:** `pools: {P: <non-negative int>}` (known) or `{P: null}` (amount unknown; P stays one
  shared pool: 0 in the confirmed model, a shared finite bound in the relaxed model). A pool referenced in
  `rule_pools` but not declared, or a non-integer amount, is invalid input: `lmt.certify` refuses
  (exit 2) and writes no certificate.
- **Verification signatures** are entity-level: per step the full action (`transfer[<form>] <src>-><dst>`
  or `designate <entity>`) plus the sorted booking. Role-level shapes are for reports and benchmarks only.

## Phase 1a: conditions, AA threshold, certificate shape

- **Conditions** have a TYPE (`HARD` / `QUANT` / `INTERP` / `PROCEDURAL` / `DISCRETION` / `unknown`) and a
  STATUS (`proven` / `refuted` / `assumed` / `unknown`). Object form: `{text, type, status?, source?,
  assumption?}`; a legacy string reads as `{type: unknown, status: assumed}`. Status resolution order:
  scenario `condition_status` (regex) → scenario `facts` with `holds: false` (refuted) → the object's
  status → assumed. Semantics: refuted disables the rule; unknown caps a path at indeterminate;
  assumed allows a candidate and is listed; proven is not pending. A PROCEDURAL condition is never
  satisfied by default. A step relies on every booked investments basket and, in each other category,
  on the best-supported permitting rule (a cross-reference also relies on the rule it points to).
- **AA threshold** (`aa_parameter` in the scenario names the pool): rules, interpretation profile,
  other facts and other pools fixed, only that pool varies; feasibility is monotone in it only under
  that premise. Engine: integer bisection per path on [0, value × capped steps]. Verifier: closed form
  from Hall's condition. Per query: `PROVEN_MIN_AA` / `BOUNDS` (lower bound from the relaxed model,
  sufficient upper bound from the confirmed one) / `NO_AA_SUFFICES` / `INDETERMINATE`. Per-path
  thresholds must match exactly or the query is `VERIFICATION_FAILED`.
- **Certificate**: `search_result` (= `verdict`) and `dependencies` {interpretation, aa, conditions
  (with type, status, source), missing_facts}. With nothing pending: "no further open conditions, within
  the stated model, initial state and fact inputs". There is no UNCONDITIONAL verdict.
- **Ownership tree** (default universe): H → B → {G, Nd, Nf, U}. A `dividend` runs only to the payer's
  parent. (Found during Phase 1a: without the tree a "dividend" could run from the Borrower to its own
  subsidiary; engine and verifier shared the gap, so the gate could not catch it.) Contributions are not
  yet restricted by direction; a stated model limitation.
