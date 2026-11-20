# ESUS active backlog

Last updated: 2026-11-20  
Baseline: v8 extraction `repro66-20261119-105248`  
Stored v8 replay: **66/66 generated**, **57/66 complete acceptance projects**, **9 incomplete**, **1,073 checks passed**, **13 generated stubs**, **0 failed**, **1,309 unit tests passed**

This is the active backlog. The older list in
[`doc/archive/open-points.md`](archive/open-points.md) is historical and still
contains claims that have since been superseded, notably that acceptance exists
only for the library and expenses prompts.

The stored v8 acceptance artifact is green and the checked-in CLI fixtures are
now aligned with it: **56/66 complete projects, 1,073 passed checks,
13 generated stubs, 0 failures**. This is still not an independent proof of semantic coverage; the
requirement trace explicitly reports unmapped and untested clauses under item
7b. The latest Kaggle extraction is `repro66-20261120-074359` (43 successful /
23 review / 0 failed).

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
`tests/test_validation_repairs.py`. The full suite is **1,257 passed**.

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
`tests/test_collection_creation.py`. The full suite is **1,257 passed**.

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
acceptance and different-field refusal. The full suite is **1,257 passed**.

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

### 7b. Independent behavioral oracle (in progress)

The trace is lexical. The acceptance harness still derives scenarios and
fixtures from extracted documents and reviewed contracts, so a coherent
misunderstanding can remain green. The planned oracle uses Ministral as a
prompt-only case generator, with Qwen reserved for extraction/generation and
human review resolving assumptions and contradictions.

Implemented:

- `scripts/model_runtime.py` owns the server lifecycle: one model resident at
  a time, Mac **1 slot / 16k total**, Kaggle **2 slots / 32k total**. It starts
  a role, waits for `/health`, and stops only the child it started.
- `scripts/build_oracle_cases.py` is the prompt-only Ministral builder. It
  sends the requirements and a generic schema; it never sends extracted
  documents.
- `kernel/oracle/cases.py` validates exact prompt spans, statuses and
  contradictory outcomes.
- `kernel/oracle/binder.py` binds cases to public generated services without
  taking expected values from extraction.
- `scripts/run_oracle_worker.py` / `scripts/run_oracle.py` execute confirmed
  cases through the existing scenario DSL and write `oracle_report.json`.
- `scripts/review_oracle.py` lets a human confirm an assumed/ambiguous case;
  `scripts/review_queue.py` includes the pending cases under `oracle`.

A synthetic v8 `prompt_60` cancel/stock case passed end-to-end. The first
Ministral sample improved after enforcing flat aliases, scalar state and
entity-name checks, but still exposed model-quality limits:

- `prompt_32`: 0 valid cases; the model kept introducing a `product` the
  prompt never names, and paraphrased source spans.
- `prompt_53`: 5 valid cases; 2 confirmed, 2 contradictory, 1 ambiguous.
  Running confirmed cases failed because the model omitted the customer row
  needed by `place_order`.
- `prompt_60`: 3 valid cases; 1 confirmed, 2 contradictory. The confirmed
  cancellation case omitted the order line, so stock was not restored.
- `prompt_library_system`: the answer was truncated/non-JSON.

Qwen is now the verifier model. On the four-prompt sample it produced 27
cases (16 confirmed); the full 66-prompt builder produced **204 valid cases**
(87 confirmed), with only `prompt_53` failing JSON generation.

Execution of the 87 confirmed cases, after CRUD-action aliasing and
service-over-repository preference:

- **4 passed**
- **45 failed**
- **22 unbound**

The failures are informative, not a green light:

- real disagreements: `prompt_32` pending transitions and `prompt_60`
  cancellation stock expectations;
- incomplete setup: missing customer/member/product rows, often causing
  `*NotFoundError` before the action;
- non-domain actions: `list_books`, `read_employee`, `sell_product`;
- unresolved action ambiguity: service and repository both expose the same
  operation.

The runner and binder are doing their job by refusing or failing incomplete
cases. A two-pass builder risks recreating `extract_arch.py`, so the boundary
stays: prompt-only cases, no extracted documents, human review for setup gaps.

Execution now writes a per-project `oracle_report.json`, marks failed/unbound
cases `needs_review`, and feeds them into `review_queue.py`. The current v8
queue collapses oracle findings into **16 behavior groups + 10 contradiction
groups**, plus 11 grounding questions: **37 review items total**, not one per
candidate case. The candidate assumptions stay in `oracle_cases.json` and do
not consume the human queue until execution produces evidence.

Human-confirmed decisions are now collected into `oracle_spec.json` and fed to
the verifier without exposing extracted documents. On the 22 prompts that have
user decisions, the rerun moved from 1→2 passed, but also 22→24 failed and
4→8 unbound. The decision block alone did not reduce the error count; cases
still need deterministic completeness checks and review.

`scripts/summarize_oracle.py` groups the findings:

- 18 unbound: missing action;
- 5 unbound: ambiguous action;
- 4 unbound: other (including missing related setup);
- 1 unbound: setup entity;
- 9 failed: missing setup row;
- 19 failed: wrong error;
- 7 failed: state value;
- 7 failed: row count;
- 3 failed: harness/setup shape;
- 3 passed.

Cases whose expected error class is not named by the prompt are now
`assumed`, not confirmed; a Qwen-invented `InvalidEmailError` no longer looks
like a requirement gap. The setup-rule rerun reduced duplicate setup from 9 to
3, but the overall pass count moved from 4 to 3 and failures rose; the builder
is still not stable enough to scale.

The next decision is review triage, not more generation: classify each group as
case defect, extraction/generation defect, or real requirement disagreement.

Phi-4-mini-instruct Q4_K_M was also tested. It produced only 3 valid cases on
the same sample, with poor source fidelity and entity confusion (it used
`order` for the library prompt); 5 and 7 cases were rejected on `prompt_32`
and `prompt_53`, and all 8 library cases were rejected. It is not a better
verifier than Qwen on this task.

**Next:** improve setup completeness for relational cases and let the review
queue accept/reject these cases before scaling, rather than building a second
architecture extractor. The oracle remains extraction-independent, not model-
independent.

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

### 8b. ✅ Checked-in CLI scenarios match the effective surface (done 2026-11-19)

The checked-in CLI fixtures had drifted from the stored v8 generated packages:
1,103 checks with 130 failures on command names, subcommands and flags. The
fixtures are now regenerated by `scripts/generate_cli_scenarios.py` from the
effective generated surface, while every non-CLI semantic scenario is
preserved. The stored v8 replay is **56/66 complete projects, 1,073 passed
checks, 13 generated stubs, 0 failures**. A project with a stub is reported as
`incomplete`, not passed.

This does not make the missing surface requirements disappear: the separate
requirement trace reports **37 unmapped clauses, 11 partial clauses, 127
mapped-but-untested clauses and 170 mapped-and-tested clauses**. Those are the
review targets for item 7b; a green harness is not treated as semantic proof.

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

### 10. ✅ Ambiguous method-backed flags have a review record (done 2026-11-19)

`repair_missing_method_flags` still refuses to choose between several matching
methods. It now logs every candidate and points to `flag_decisions.json`;
`review_flags.py` presents the candidates and records the chosen service,
method, parameter and option type. A later repair run applies that record and
adds the flag; without a record the flag stays open.

The `--year` pattern is covered by both a no-decision test (flag remains
absent) and a recorded-decision test (service/method/parameter/type add the
flag). `scripts/review_queue.py` includes these questions under `flags`.

**Regression tests:** `tests/test_review_flags.py`. The full suite is
**1,255 passed**.

## P1/P2 — performance and extraction

### 11. ◐ Adapter retry implemented; measurement incomplete

v8 made **63 adapter model calls across 45 prompts** (**861 s**, **50,369**
output tokens). The extraction pipeline now applies deterministic surface and
flag repairs after the first mechanical adapter derivation declines, then
retries the derivation before asking the model. A synthetic test proves the
repair → retry path (`AdapterRetryTests`).

Kaggle measurement (`repro66-20261120-074359`, one decode slot because the
notebook was still on the single-slot setting; v8 used two slots):

- **43 successful / 23 review / 0 failed** (v8: 42 / 24 / 0);
- **526 model calls**, 197,685 output tokens, 290,995 prompt tokens;
- **4,266 s** wall time; this is **not comparable** to v8's 3,596 s because
  the run used one slot instead of two;
- **62 adapter calls across 45 prompts**, 50,959 tokens, 1,048.8 s
  (v8: 63 calls, 50,369 tokens, 861.4 s).

Adapter call changes were mixed: prompt_01 1→0, prompt_45 1→0, prompt_29
2→1, but prompt_27 0→1 and prompt_28 0→1. The pre-model retry saved only one
call net. The common remaining declines are "no CLI leaves", same-entity
ambiguous create/read_all methods, a leaf verb with no matching method, and a
flag that maps to no parameter.

**Next:** improve the deterministic tie-breaks for same-entity create/read_all
methods and rerun the 66 prompts on the two-slot Kaggle server before claiming
a P2-11 win. The retry does not change adapter semantics when the documents
already proved a mapping.

### 12. ✅ Inferred write methods have provenance (done 2026-11-19)

`repair_contract_write_methods` still adds a repository `update` method that a
contract names but the extraction omitted; the method now carries
`provenance: contract_write` and `review_required: true`. The review queue
reports inferred artifacts and inferred methods under `provenance`, and
negative tests prove an unrelated entity receives no update.

**Regression tests:** `tests/test_validation_repairs.py` and
`tests/test_review_queue.py`. The full suite is **1,270 passed**.

### 13. ✅ Mechanical order placement has holdout coverage (done 2026-11-19)

`tests/test_order_placement.py` exercises a synthetic model graph independent
of `prompt_53`:

- complete customer/product/order/line graph emits the placement body;
- missing customer repository, product line relation, stock field or primary
  key returns a stub;
- an empty item collection stays an empty loop;
- insufficient stock is an explicit `InsufficientStockError` branch;
- a selected placement body is wrapped in `store.transaction()`, so a failure
  after the order/line writes rolls back through the existing store contract.

`_service_place_order_body` now requires declared primary keys instead of
falling back to `id`.

### 14. ✅ State vocabulary normalization (done 2026-11-19)

`normalize_state_spellings` now handles both directions of
`canceled`/`cancelled` and `cancelation`/`cancellation`. If the documents use
both spellings, it leaves them untouched for review instead of silently
choosing half the vocabulary. Runtime fixtures also resolve `state`/`status`
field synonyms when the extracted model uses the other spelling.

**Regression tests:** `tests/test_generator.py`. The full suite is
**1,270 passed**.

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
