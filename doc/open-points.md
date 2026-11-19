# ESUS active backlog

Last updated: 2026-11-19  
Baseline: v8 extraction `repro66-20261119-105248`  
Local replay: **66/66 generated**, **66/66 acceptance projects**, **1,073 checks passed**, **0 failed**, **0 not applicable**, **1,203 unit tests passed**

This is the active backlog. The older list in
[`doc/archive/open-points.md`](archive/open-points.md) is historical and still
contains claims that have since been superseded, notably that acceptance exists
only for the library and expenses prompts.

The 66/66 result is green on the current harness, but it is not yet an
independent proof of semantic coverage. The priorities below reflect that
distinction.

## P0 — correctness and trust

### 1. Contract checks can produce false positives

- **F-01:** a `set` effect can be satisfied by the expected value appearing
  anywhere in the body, including a log message or unrelated constant.
- **F-02:** a field mentioned as text or a constant can count as a read even
  when the related record was never read.
- **F-03:** the `raise_when` polarity is not always proven from the dominant
  control-flow path.

**Next:** bind the proof to the actual assignment/read/raise node and dataflow.
When the proof is inconclusive, report `unknown` or require review rather than
accepting the body.

### 2. Repairs can be destructive or over-broad

- **F-04:** a missing contract can cause a real state guard to be removed.
- **F-05:** an empty extraction can become an inferred persisted domain.
- **F-06:** capability adapters can add service behavior without proving all
  of its semantics.
- **F-07:** inferred fields can propagate through several layers and become
  indistinguishable from confirmed fields.

**Next:** distinguish `quoted`, `extracted`, `inferred`, `human-confirmed` and
`unknown`. Never promote inferred data to confirmed data without a review.
A repair must preserve its provenance and justification.

### 3. Lexical heuristics still misclassify

- **F-09:** `classify_crud` still matches substrings such as `all` and `list`.
  Current examples: `get_small_businesses` and `blacklist_user` classify as
  `read_all`.
- **F-10:** `match_param` can map a range prefix to the wrong field. Current
  example: `match_param(["stage"], "min_age")` returns `("stage", "ge")`.

**Next:** classify on normalized tokens and exact entity/verb structure.
When no exact mapping exists, leave the method as a stub or ask for review.

### 4. Negation is lost in invariant parsing

- **F-11:** “must not be positive” is parsed as a positive numeric bound.
- **F-12:** “must not be greater than” is parsed as a greater-than relation.

**Next:** represent negation and operator scope explicitly, and test positive
and negative minimal pairs. Do not generate a rule from a sentence the parser
does not understand.

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
