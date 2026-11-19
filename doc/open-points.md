# ESUS active backlog

Last updated: 2026-11-19  
Baseline: v8 extraction `repro66-20261119-105248`  
Stored v8 replay: **66/66 generated**, **66/66 acceptance projects**, **1,073 checks passed**, **0 failed**, **0 not applicable**, **1,252 unit tests passed**

This is the active backlog. The older list in
[`doc/archive/open-points.md`](archive/open-points.md) is historical and still
contains claims that have since been superseded, notably that acceptance exists
only for the library and expenses prompts.

The stored v8 acceptance artifact is green, but it is not yet an
independent proof of semantic coverage. The checked-in scenario suite now
contains additional CLI fixtures beyond that 1,073-check artifact; replaying
the stored v8 code against them is not green yet and is tracked under item 8.
The priorities below reflect both distinctions.

## P0 — correctness and trust

### 1. ✅ Contract checks are proof-based (done 2026-11-19)

- **F-01:** a `set` effect was satisfied by the expected value appearing
  anywhere in the body, including a log message or unrelated constant.
  The check now compares only the assigned RHS, including target-relative
  expressions such as `not member.is_active`.
- **F-02:** a field mentioned as text or a constant could count as a read even
  when the related record was never read. Reads now follow repository/store
  calls through aliases, loops, attribute/subscript access and field filters.
- **F-03:** an unconditional raise could satisfy a conditional precondition.
  A `raise_when` contract now requires a recognized conditional guard; an
  unconditional raise is refused.

**Regression tests:** `tests/test_contract_proofs.py`. The full suite is
**1,213 passed**. Re-running the stored v8 method bodies through the stricter
gate produced no new complaints and fixed the valid
`renew_membership` expression case; the remaining complaints are pre-existing
stub/delegation/derive gaps tracked elsewhere.

### 2. ✅ Repairs are non-destructive and provenance-aware (done 2026-11-19)

- **F-04:** a missing contract caused a real state guard to be removed.
  `repair_invented_state_guards` now removes a guard only when the same
  holder/method has a human-confirmed contract with no preconditions. Missing,
  inferred, auto and other-method contracts preserve the guard.
- **F-05:** an empty extraction could become a persisted domain from the
  article "the". Domain-candidate extraction now rejects articles and
  demonstratives, so "the application" is not a `The` entity. Inferred models,
  persistence and CRUD components carry `provenance: empty_domain_repair` and
  `review_required: true`.
- **F-06:** capability-derived methods and adapters are marked
  `provenance: capability_adapter` and `review_required: true`. Remaining
  semantic choices such as duplicate policy, atomicity and error behavior are
  therefore explicit review candidates rather than silent extraction facts.
- **F-07:** model fields propagated into create ports, mapping parameters and
  adapter fields carry the original `status` (`explicit`, `inferred from
  prose`, and so on), so a later layer cannot silently promote an inference.

**Regression tests:** `tests/test_state_guard_repair.py` and
`tests/test_validation_repairs.py`. The full suite is **1,252 passed**.

**Follow-up:** the review queue in item 9 must consume `review_required` and
present the unresolved capability semantics before final acceptance.

### 3. ✅ Lexical classification uses whole words (done 2026-11-19)

- **F-09:** `classify_crud` matched substrings such as `all` and `list`, so
  `get_small_businesses` and `blacklist_user` became `read_all`. Read-all is
  now recognized only by a whole prefix (`read_all`) or whole word
  (`get_all_customers`, `list_products`).
- **F-10:** `match_param(["stage"], "min_age")` returned `("stage", "ge")`
  because the range remainder was a substring. A range remainder must now
  equal the field or end on a complete field-word suffix: `min_stage` matches
  `stage`, `start_date` matches `expense_date`, `min_age` matches nothing.

Ambiguous names still fall through to the stub/parameter-shape path rather
than being assigned a mechanical body.

**Regression tests:** `tests/test_generator.py::PlanTests`. The full suite is
**1,223 passed**.

### 4. ✅ Invariant parsing preserves negation (done 2026-11-19)

- **F-11:** “must not be positive” was parsed as `> 0`. It now produces no
  numeric bound, while “must be positive” still produces `> 0`. The schema
  invariant collector applies the same rule, so it no longer emits a
  positive schema line from a negated sentence.
- **F-12:** “must not be greater than” was parsed as `>`. Comparison parsing
  now recognizes negated forms first: “not greater than”, “no more than” and
  “at most” become `<=`; “not less than”, “no less than” and “at least”
  become `>=`. The same parser drives the deterministic price guard.

**Regression tests:** `NumericBoundTests`, `FieldRelationTests`,
`test_schema_invariants.py` and `test_mechanical_reports.py`. The full suite is
**1,229 passed**.

### 5. ✅ Formulas and collection creates require evidence (done 2026-11-19)

- **F-13:** `line_total = quantity * unit_price` was derived from three field
  names. It is now derived only when an invariant explicitly states the
  multiplication (“multiplied by”, “times”, “product of” or `*`). With no such
  rule the value is left unresolved rather than guessed.
- **F-14:** a plural parameter such as `order_items` is no longer enough to
  create records. The related model must have a foreign key to the method’s
  owning entity and at least one payload field. `place_order(order_items)` on
  `OrderService` still resolves; `tags` on a service whose `Tag` model has no
  parent FK is refused.

**Regression tests:** `CreateDefaultTests` and
`tests/test_collection_creation.py`. The full suite is **1,252 passed**.

### 6. ✅ Bodies are not judged by their own writer (done 2026-11-19)

- **F-08:** `fill_stubs()` used the same loaded model for body generation and
  for the equivalence judge. The body pass no longer synthesizes that judge.
  Alternate guards are accepted only by deterministic structural equivalence,
  including local aliases (`event.status` vs `registration.status`); anything
  else is refused and left as a review gap.
- `_raise_when_complaints` still accepts an optional judge for an external
  independent consumer, but the writer never supplies itself as that judge.
- The old equivalence-prompt parser remains as a utility and is covered by
  its existing tests; it is simply no longer invoked by `fill_stubs()`.

**Regression tests:** `tests/test_guard_equivalence.py`, including alias
acceptance and different-field refusal. The full suite is **1,252 passed**.

## P1 — validation and review

### 7. ✅ Requirement traceability report (done 2026-11-19)

`scripts/requirement_trace.py` splits every `requirements.txt` into sentences
and command examples, indexes the extracted models, fields, commands, options,
methods, errors, invariants, contracts, adapters and components, and reports:

- `mapped_tested`: a clause maps to an artifact that a runtime check names;
- `mapped_untested`: design evidence exists but no check names it;
- `partial`: only a weak lexical overlap;
- `unmapped`: no significant token overlap.

`scripts/run_bench_acceptance.py` now writes `coverage.json` and adds a
separate `coverage` block to `summary.json`; the pass/fail verdict is
unchanged. On the stored v8 extraction the standalone report covers 345
clauses: 297 mapped-but-untested, 37 unmapped and 11 partial. Those gaps are
now visible instead of being implied by a green acceptance run.

**Regression tests:** `tests/test_requirement_trace.py`. The full suite is
**1,241 passed**.

### 7b. Independent behavioral oracle (open)

The trace is lexical. The acceptance harness still derives scenarios and
fixtures from extracted documents and reviewed contracts, so a coherent
misunderstanding can remain green. A true oracle needs independently authored
behavioral requirements and tests, or a different model/process that does not
share the extraction's interpretation.

**Next:** add a small independently authored behavior suite for requirements
where the trace is `mapped_untested` or `unmapped`, starting with the highest
risk business rules.

### 8. ✅ Contract scenarios are derived generically (done 2026-11-19)

The checker no longer needs a hand-written fixture for a plain state effect:

- A `set` effect on `.status`/`.state` derives a documented starting value
  from the allowed-value vocabulary and the method description, then verifies
  the target field after the call. `cancel_order` now runs from a confirmed
  state without a prompt-specific scenario.
- Invalid preconditions are derived for `==`, `!=`, `is None`/`is not None`,
  numeric comparisons and membership sets; literal `increment`/`decrement`
  deltas are checked against the before value.
- Unique and foreign-key rules already run generically through the invariant
  checks; collection contracts still use an explicit scenario when one exists
  or report a coverage gap.
- `not_applicable` is no longer used for ordinary state effects. The stored
  v8 run has **0 `not_applicable`** checks across 1,103 checks.

**Regression tests:** `tests/test_runtime_state_scenarios.py`. The full suite
is **1,249 passed**.

### 8b. Reconcile the checked-in CLI scenarios (open)

The checked-in scenario suite currently defines 1,103 checks, but replaying
the stored v8 code gives **31/66 projects passed and 130 failed checks**. The
failures are concentrated in CLI scenarios whose command names, subcommands or
flags do not match the generated surface (`Order search`, `Order confirm`,
`Product update --stock-quantity`, and similar). These are requirement/surface
gaps, not semantic state-effect failures.

**Next:** resolve each class generically: either the generator must emit the
missing requirement-backed command/flag, or the scenario fixture is stale and
must be regenerated from the effective surface. Do not delete a requirement
check merely to make the run green.

### 9. ✅ Attended-review queue is explicit (done 2026-11-19)

`scripts/review_queue.py` collects every unresolved tie, slot, surface route,
field alias, grounding question and method contract into one JSON and optional
Markdown queue. Each item names:

- the prompt and source;
- the question and candidate evidence;
- the review script and command that resolves it;
- its provenance in the extracted documents.

It never answers or drops a question. `scripts/answer_reviews.py` remains
conservative (singleton slots only; ambiguous ties, routes, contracts and
free-form conditions stay open). On the stored v8 tree the queue contains
**11 open grounding questions**; those are now visible as the remaining
attended-review work rather than being implied by a sidecar.

**Regression tests:** `tests/test_review_queue.py`. The full suite is
**1,252 passed**.

### 10. Ambiguous flags need review, not a fuzzy choice

`repair_missing_method_flags` abstains when several methods can satisfy one
flag. The `--year` case is the reference example: three candidate methods/types
exist, so the flag/route must be chosen by a reviewer or a stronger rule.

**Next:** surface those candidates as a review question and record the chosen
service, method, parameter and option type.

## P1/P2 — performance and extraction

### 11. Adapter model calls are still expensive

v8 still made **63 adapter model calls across 45 prompts**:

- **861 s** of extraction wall time;
- **50,369** output tokens.

The post-repair mechanical derivation helps local replay, but the Kaggle
extraction still pays model calls when the first derivation declines.

**Next:** run mechanical adapter derivation again after surface repairs as part
of the extraction pipeline, or retry it before asking the model. Measure
whether the resulting adapter set is equal or better in acceptance.

### 12. Inferred write methods need provenance

`repair_contract_write_methods` can add a repository `update` method that a
contract names but the extraction omitted.

**Next:** mark the method as inferred, expose it in the probe/review, and add
negative tests ensuring it is not added to unrelated entities.

### 13. Mechanical order placement needs holdout coverage

The new order-placement/stock-check bodies are generic over the extracted
model graph, but currently exercised mainly by `prompt_53`.

**Next:** add positive and negative tests for:

- missing customer/product/line relations;
- missing stock field or primary key;
- insufficient stock;
- no line items;
- transaction rollback.

## P2 — longer-term

- **Type hints:** the fixed store/CLI templates and generated helpers still
  lack many annotations, although domain method signatures are annotated.
- **Error-message assertions:** assert exact messages where a prompt requires
  them; today most checks cover error names/markers only.
- **Nested paths:** command paths are supported to three words; true N-level
  paths are not modeled.
- **`main.py` review UX:** preserve the spinner and show only the active
  review question.
- **Caching:** cache extraction and body answers by prompt/fixture so unchanged
  reruns do not repeat model calls.
- **State vocabularies:** normalize `canceled`/`cancelled` and similar terms
  from document evidence, with a test for conflicting vocabularies.

## Definition of done for the next milestone

1. No manual document edits in the validation workflow.
2. Ambiguous decisions are either evidence-backed or explicitly queued for
   human review.
3. `not_applicable`/skipped required checks are reported as coverage gaps.
4. Acceptance reports separate:
   - generated;
   - harness-passing;
   - requirements-covered;
   - behaviorally-verified.
5. A clean 66-prompt run passes without prompt-specific sidecars that were
   authored outside the review process.
6. The actionable audit findings F-01, F-02, F-04, F-09, F-10, F-11 and F-12
   have regression tests.

## Related documents

- Audit findings: `doc/esus_findings_consolides.md` (local working document;
  currently not tracked)
- [Validation](validation.md)
- [Checks, coverage, and gaps](checks-coverage-and-gaps.md)
- [Speed](speed.md)
- [How the agent works](how-the-agent-works.md)
