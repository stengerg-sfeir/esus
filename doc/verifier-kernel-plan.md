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

## P1 — Test intent schema

The model emits an intent, not a complete case:

```json
{
  "source": "exact clause",
  "kind": "create | update | delete | list | aggregate | error | cli | app",
  "entity": "Product",
  "action": "add_product",
  "lookup": ["Product.sku"],
  "changes": {"stock_qty": 3},
  "expect": {
    "rows": {"Product": 1},
    "state": ["Product.stock_qty"],
    "error": null
  }
}
```

The intent contains no concrete IDs, no full setup rows and no fixture graph.

## P2 — Fixture planner

Given an intent and `data_models.json`:

- topologically seed FK parents;
- respect required/nullable fields;
- generate unique IDs and unique values;
- use intent values for fields the assertion depends on;
- use safe defaults only for unasserted referential fields;
- reject missing semantic values rather than inventing them.

## P3 — Test emitters

Pre-created emitters for:

- create;
- update;
- delete / soft delete;
- list / filter / search;
- aggregate;
- error / precondition;
- CLI;
- app;
- invariant boundary.

Each emitter produces the existing scenario DSL and uses the existing runtime
worker. No second sandbox.

## P4 — Diagnostics and trace

Every intent records:

- alignment status and canonical names;
- fixture graph;
- emitter used;
- assertion result;
- prompt clause.

Diagnostics distinguish:

- naming mismatch / alias;
- real extraction/generation coverage gap;
- verifier invention;
- ambiguous requirement;
- emitter coverage gap;
- actual behavior finding.

## Order

1. P0 alignment + tests.
2. P1 intent schema + extractor.
3. P2 fixture planner.
4. P3 emitters, starting with create/update/delete/list.
5. P4 diagnostics and trace integration.
6. Re-run the 54 unbound cases and the 35 untested clauses.

## Non-goals

- no manual fixtures;
- no generated-code oracle;
- no silent model secrecy about extraction coupling;
- no blanket FK auto-seeding of semantic parents.
