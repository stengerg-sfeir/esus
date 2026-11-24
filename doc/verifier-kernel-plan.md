# Verifier kernel plan

## Goal

Move the verifier from free-form case generation to the same architecture as
code generation:

```text
requirements clause
→ test intent
→ concept alignment
→ mechanical fixture planner
→ pre-created test emitter
→ deterministic assertion
→ model only for the uncovered semantic values
```

Expected behavior stays prompt-derived. Extracted documents may be used for
**binding and setup mechanics**, never to invent the expected result.

## Invariants

- The verifier must not see generated code.
- Expected state, errors, rows and output remain prompt- or human-derived.
- A test may use extracted names/fields/FKs to build fixtures.
- The kernel may connect rows it was told about; it must not invent semantic
  values the assertion depends on.
- Every case remains traceable to an exact prompt clause.

## P0 — Concept alignment ✅ implemented

Current annotation on the 79-case verifier set:

- 232 aligned references;
- 22 aliases;
- 51 ambiguous;
- 9 prompt-grounded coverage gaps;
- 24 invented references.

These are diagnostics, not verdicts. An alias is rewritten to the canonical
extracted name; a prompt-grounded missing concept is a coverage gap; an
unmentioned missing concept is a verifier invention.

Add `kernel/oracle/alignment.py`.

It aligns a verifier concept against the extracted documents using:

- normalized names, plurals and snake/camel variants;
- field overlap;
- action/verb overlap;
- relationship neighbourhood;
- exact prompt-clause evidence.

Statuses:

- `aligned` — exact concept;
- `alias` — different name, same concept;
- `ambiguous` — several plausible concepts;
- `coverage_gap` — prompt names the concept, documents have no candidate;
- `invented` — no prompt evidence and no document candidate;
- `under_specified` — prompt cannot decide.

Use it before binding. A naming alias is rewritten to the canonical extracted
name; it is not reported as a coverage defect.

## P1 — Test intent schema ✅ implemented

The model emits an intent, not a complete case:

```json
{
  "source": "exact clause",
  "kind": "create | update | delete | list | aggregate | error | cli | app",
  "entity": "Product",
  "action": "add_product",
  "setup_entities": [
    {"alias": "product", "entity": "Product", "role": "target"}
  ],
  "setup_values": {"product.stock_qty": 5},
  "lookup": ["product.sku"],
  "where": {"product.category": "tools"},
  "args": ["product.sku", 3],
  "changes": {"product.stock_qty": 3},
  "expect": {
    "state": {"product.stock_qty": 8},
    "rows": {"Product": 1},
    "error": null
  }
}
```

The intent contains no concrete IDs, no full setup rows and no fixture graph.
`kernel/oracle/intents.py` validates it, rejects non-class error sentences and
operation/input mismatches, and downgrades a `confirmed` intent when its error,
date, argument or stdout is not grounded in the target clause.

`scripts/build_test_intents.py` generates intents prompt-only, one target clause
at a time.

## P2 — Fixture planner ✅ implemented

`kernel/oracle/fixtures.py` and `scripts/build_intent_cases.py`:

- topologically seed FK parents;
- respect required/nullable fields;
- generate deterministic unique values;
- use intent values for fields the assertion depends on;
- canonicalize prompt field spellings to extracted field names;
- seed missing method-parameter entities (`borrow_book` needs a `Member`),
  while never filling a row whose not-found error is the expected rejection;
- reject ungrounded actions, unknown fields and cyclic required foreign keys;
- use safe defaults only for unasserted referential fields.

Every synthetic row is recorded in `oracle_intent_plans.json`. No synthetic row
is allowed to supply an asserted semantic value.

## P3 — Test emitters ✅ reused

The existing binder and runtime worker are the emitters:

- create / update / delete;
- list / filter / search;
- aggregate;
- error / precondition;
- CLI;
- app;
- the existing scenario DSL and sandbox.

No second execution path was added.

## P4 — Diagnostics and trace ✅ implemented for confirmed evidence

Every planned intent records its source, canonical aliases, synthetic fixtures,
execution status and assumption list. The trial separates:

- confirmed passes;
- assumed passes and failures;
- plan rejections from ungrounded actions or fields;
- true confirmed behavior findings.

`scripts/requirement_trace.py` now reads confirmed intent reports
(`oracle_cases_intents.json` / `oracle_report_intents.json`) alongside the main
oracle. The confirmed intent set closes 5 mapped-but-untested clauses:

- before: **293 tested / 35 untested**;
- after: **302 tested / 0 unknown; 30 classified blockers**.

Assumed intent cases are kept in the advisory sidecar, not promoted into the
main trace. The confirmed-only report is produced with:

```bash
python scripts/run_oracle.py out/validation/kaggle-v8 \
  --cases oracle_cases_intents.json \
  --report-name oracle_report_intents.json
```

Run the acceptance bench after that report is present to regenerate the trace.

## P5 — Canonical merged verifier ✅ implemented

`scripts/build_verifier_cases.py` builds `oracle_cases_merged.json` from:

- previously passing cases;
- confirmed intent cases.

Retired unbound cases are not silently deleted; they are written to
`oracle_cases_retired.json` with their last status and reason.

`scripts/run_verifier.py` runs that merged path end to end.

Current canonical result:

- **50 passed / 0 failed / 0 unbound**;
- 54 retired unbound cases in the audit sidecar;
- requirement trace remains **302 tested / 0 unknown; 30 classified blockers**.

The merged verifier is green because retired cases are not evidence. The
30 classified blockers are the remaining coverage backlog.

The backlog is classified with:

```bash
python scripts/classify_coverage.py out/validation/kaggle-v8 \
  --coverage out/validation/kaggle-v8/acceptance/coverage.json
```

Current 30-clause classification:

- 9 assumed-only;
- 12 under-specified;
- 5 blocked by generation;
- 0 blocked by extraction;
- 0 unknown / `mapped_untested`.

`assumed_only` and `under_specified` are verifier/specification work;
`blocked_extraction` and `blocked_generation` are product fixes. Assumed
passes still need prompt evidence before they can be promoted.

## Trial result

Across the 35 mapped-untested clauses:

- 65 intents generated;
- 63 intent cases planned;
- 38 passed;
- 19 assumed-only failures;
- 5 unbound by a mechanical preflight;
- **0 confirmed behavior findings**;
- 25 confirmed intent passes are used by the merged verifier;
- the merged verifier closes 5 clauses: **302 tested / 0 unknown; 30 classified blockers**.

The verifier-side hardening in this pass:

- over-broad model sources are anchored to the target clause;
- appended intent runs keep IDs unique;
- ungrounded aliases are rewritten to extracted entity names;
- unmentioned auxiliary identity/filter fields are dropped or replaced by
  the primary key, while prompt-named missing fields stay hard gaps;
- action matching ranks method-name specificity instead of treating every
  token overlap as ambiguous;
- a target not used by the chosen action is downgraded to assumed;
- list expectations seed additional rows mechanically, but replication also
  downgrades the case to assumed;
- bulk collection parameters that cannot be supplied mechanically are
  rejected before execution.

The main verifier remains at **25 passed / 0 failed / 54 unbound**. The
stable acceptance result remains **66/66 projects, 3,052 checks passed (2 skipped), 0 stubs**.

## Order

1. ✅ P0 alignment + tests.
2. ✅ P1 intent schema + extractor.
3. ✅ P2 fixture planner.
4. ✅ P3 emitters, reusing binder + worker.
5. ✅ P4 diagnostics and confirmed-intent trace integration.
6. ✅ P5 canonical merged verifier with retired-case audit.
7. Classify the remaining 30 clauses as confirmed coverage, extraction
   gap, generation gap, or under-specified; expand intents only where the
   prompt supports a confirmed assertion.

## Non-goals

- no manual fixtures;
- no generated-code oracle;
- no silent model secrecy about extraction coupling;
- no blanket FK auto-seeding of semantic parents.
