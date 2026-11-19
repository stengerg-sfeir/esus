# ESUS active backlog

Last updated: 2026-11-19  
Baseline: v8 extraction `repro66-20261119-105248`  
Stored v8 replay: **66/66 generated**, **66/66 acceptance projects**, **1,073 checks passed**, **0 failed**, **0 not applicable**, **1,229 unit tests passed**

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
`tests/test_validation_repairs.py`. The full suite is **1,229 passed**.

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

### 5. Formula and relationship inference

- **F-13:** `line_total = quantity * unit_price` can be inferred from field
  names without an explicit formula contract.
- **F-14:** collection creation can be inferred from a plural parameter name
  without proving the relation or item shape.

**Next:** require an explicit or reviewed formula/relationship contract.
Otherwise leave the value unresolved and report the missing rule.

### 6. The same LLM writes and judges bodies

- **F-08:** `fill_stubs()` uses the same model for body generation and the
  equivalence judge.

**Next:** separate generation and judgment, or replace the judge with a
deterministic check plus independent behavioral tests. Keep LLM verdicts as
evidence, not proof.

## P1 — validation and review

### 7. Independent acceptance oracle and requirement traceability

The current harness is data-driven and runs all 66 projects, but its scenarios
and fixtures are derived from extracted documents and reviewed contracts. It
can pass a coherent misunderstanding.

**Next:** add a requirements-to-artifact-to-test traceability matrix. A green
run should report coverage separately from harness success. Do not treat
internal consistency as business truth.

### 8. Semantic scenarios are still sparse

The two former `not_applicable` checks now have semantic scenarios:

- `OrderService.cancel_order` — status change and stock restoration;
- `LibraryService.return_book` — return status and available-copy increment.

**Next:** generate semantic scenarios for every state effect, error/precondition,
transactional multi-write contract and unique/FK rule where the model supports
it. `not_applicable` should become an explicit coverage gap, not a quiet pass.

### 9. Ambiguous review decisions need a real queue

`scripts/answer_reviews.py` is now conservative:

- it answers only singleton slot candidates;
- ambiguous ties, routes, contracts and free-form conditions stay open;
- it never drops a requirement flag or upstream gap just to make the probe
  green.

**Next:** provide a clear attended-review queue with candidate evidence and
provenance. The current 66/66 replay uses evidence-backed review sidecars; it
is not an entirely unattended path for genuinely ambiguous cases.

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
