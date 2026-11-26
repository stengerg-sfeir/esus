# Final Mac chain — 2026-11-26

## Result

**Acceptance passed; the verifier is clean: 0 behavior findings and 0 case defects. 19 coverage gaps and 14 under-specified cases remain as extract/generator signals.**

The run completed extraction, sidecar/repair/readiness, generation and acceptance. Acceptance is green. The verifier now regenerates prompt-derived cases for all 66 prompts. The fresh case set produced **64 passed, 14 under-specified, and 19 coverage gaps** from 129 accepted cases. No behavior findings or case defects remain. The canonical merged verifier ran cleanly: **81/81 passed**.

- Run root: `out/validation/runs/mac-final5-20261126`
- Model: `Qwen3-4B-Instruct-2507-Q4_K_M.gguf`, llama-server under `caffeinate`
- Acceptance: **66/66, 3,242 passed, 2 skipped, 0 stubs**

## Verifier changes

- The verifier now has a clean four-way split:
  - **`behavior:*`** — generated code ran and disagreed with a valid case.
  - **`case_defect:*`** — the verifier case itself is malformed or internally inconsistent.
  - **`under_specified`** — the prompt does not determine the field, payload, CLI protocol, or error contract.
  - **`coverage_gap:*`** — the prompt names an action, field, entity, or signature that extraction/generation omitted.
- The case validator and binder now:
  - reject updates with no new value, hard-delete state assertions, unsupported list reductions, unknown row entities, and inconsistent create values
  - audit filter cases against their own seeded rows
  - **repair a zero-row filter case by adding a contrasting row and setting the expected count to the matching rows**, so the case remains a real filter test instead of becoming a false behavior finding
  - map boolean `*_only` flags to the corresponding generated boolean filter
  - seed missing FK parents, not-found preconditions, order items, and deterministic import/export fixtures
  - classify sort-direction-only cases as missing sort-surface gaps
  - classify non-class error expectations as under-specified
  - count paginated `items` lists and prefer the create target's fields over related rows
- `verifier_variance.json` meters the whole case lifecycle: **201 generated, 129 accepted by the verifier, 97 executed**.

## Verifier result

Prompt-derived oracle run:

- Generated cases: **201**; accepted: **129**; executed: **97**
- Triage:
  - `passed`: 64
  - `under_specified`: 14
  - `coverage_gap: missing action`: 4
  - `coverage_gap: ambiguous action`: 8
  - `coverage_gap: method signature`: 4
  - `coverage_gap: schema`: 3
  - `case_defect`: **0**
  - `behavior:*`: **0**

**Under-specified cases (not verifier defects):**
- CLI protocol not determined: `prompt_02`.
- Undetermined task fields: `prompt_04`.
- Undetermined order date field: `prompt_21`.
- Undetermined order-items payload: `prompt_53`.
- Invalid-row rejection without an error contract: `prompt_18`.
- Other invented or vague actions: 9 cases.

**Coverage gaps (real extraction/generation signals):**
- 4 missing actions
- 8 ambiguous action bindings
- 4 missing sort/signature surfaces
- 3 schema/model gaps

**Canonical merged verifier:**
- **81 cases, 81 passed, 0 case defects, 0 behavior findings**
- One stale legacy `prompt_14` soft-delete case was retired: it supplied an unsupported `status` filter to `list_projects`.
- The canonical verifier command exits successfully.

## Extraction and sidecar variance

- 66 prompts: **41 successful, 24 review, 1 not_generatable**, resolved by deterministic repair
- Per-prompt time: **5286.149 s**; tokens: **174,480 out / 274,146 prompt**; calls: **498**
- Readiness: **0 blockers, 0 open ties, 96 risks**; review/repair/probe: **2.376 / 16.923 / 2.928 s**
- Sidecars copied/reapplied: **59**
- Structural variance versus `kaggle-v8`:
  - 42 command surfaces changed
  - 4 model sets changed
  - 8 service sets changed
  - 2 repository interfaces changed
  - 51 adapter sets changed

## Generation and acceptance

- Generation: **66/66**, **983.809 s**, **9,546** output tokens, **260,745** prompt tokens, **55** calls, 0 failures
- Acceptance CLI scenarios were regenerated from the current surface; stale fixtures were not replayed.
- Acceptance checks: **3,242 passed, 2 skipped, 0 failed**; 0 stubs.

## Not run

- Full extraction/generation chain rerun
- Final canonical trace against the regenerated cases

These are intentionally not launched without explicit approval before the GPU transfer.

## Artifacts

- `summary.json`, `chain_metrics.json`, `sidecar_variance.json`, `final_readiness.txt`
- `acceptance3/summary.json`
- `oracle_cases.json`, `oracle_report.json`, `oracle_findings.md`, `verifier_variance.json`
- `oracle_cases.previous.json`, `oracle_report.previous.json`

## Per-prompt extraction

| Prompt | Class | Seconds | Tokens out | Prompt tokens | Calls | Blockers | Ties |
|---|---:|---:|---:|---:|---:|---:|---:|
| `prompt_01` | successful | 9.666 | 163 | 2191 | 5 | 0 | 0 |
| `prompt_02` | successful | 12.140 | 382 | 2274 | 5 | 0 | 0 |
| `prompt_03` | successful | 43.759 | 1457 | 3340 | 7 | 0 | 0 |
| `prompt_04` | review | 43.253 | 1521 | 3840 | 8 | 0 | 1 |
| `prompt_05` | successful | 21.653 | 773 | 3259 | 7 | 0 | 0 |
| `prompt_06` | successful | 23.319 | 822 | 3232 | 7 | 0 | 0 |
| `prompt_07` | successful | 25.847 | 893 | 3259 | 7 | 0 | 0 |
| `prompt_08` | successful | 22.188 | 762 | 3315 | 7 | 0 | 0 |
| `prompt_09` | review | 35.077 | 1185 | 3392 | 7 | 0 | 2 |
| `prompt_10` | successful | 44.337 | 1613 | 3917 | 8 | 0 | 0 |
| `prompt_11` | review | 74.013 | 2653 | 3996 | 8 | 0 | 1 |
| `prompt_12` | successful | 73.247 | 2633 | 3860 | 8 | 0 | 0 |
| `prompt_13` | successful | 85.119 | 3056 | 4506 | 9 | 0 | 0 |
| `prompt_14` | successful | 50.746 | 1749 | 4058 | 8 | 0 | 0 |
| `prompt_15` | successful | 20.911 | 699 | 3225 | 7 | 0 | 0 |
| `prompt_16` | successful | 50.522 | 1772 | 4418 | 9 | 0 | 0 |
| `prompt_17` | successful | 56.138 | 1953 | 3873 | 8 | 0 | 0 |
| `prompt_18` | successful | 73.108 | 2427 | 3925 | 8 | 0 | 0 |
| `prompt_19` | review | 153.916 | 4970 | 3334 | 7 | 0 | 3 |
| `prompt_20` | successful | 90.769 | 3043 | 3361 | 7 | 0 | 0 |
| `prompt_21` | successful | 71.497 | 2507 | 3408 | 7 | 0 | 0 |
| `prompt_22` | successful | 133.368 | 4418 | 4924 | 9 | 0 | 0 |
| `prompt_23` | review | 118.249 | 3974 | 3534 | 7 | 0 | 1 |
| `prompt_24` | successful | 79.736 | 2646 | 4102 | 8 | 0 | 0 |
| `prompt_25` | review | 46.925 | 1574 | 3264 | 7 | 0 | 1 |
| `prompt_26` | review | 102.711 | 3386 | 3630 | 7 | 0 | 1 |
| `prompt_27` | successful | 210.836 | 7019 | 4261 | 8 | 0 | 0 |
| `prompt_28` | review | 83.794 | 2845 | 3654 | 7 | 2 | 1 |
| `prompt_29` | successful | 63.949 | 2120 | 3437 | 7 | 0 | 0 |
| `prompt_30` | successful | 16.716 | 567 | 3253 | 7 | 0 | 0 |
| `prompt_31` | successful | 38.429 | 1307 | 3348 | 7 | 0 | 0 |
| `prompt_32` | successful | 29.963 | 958 | 3351 | 7 | 0 | 0 |
| `prompt_33` | successful | 73.609 | 2571 | 4140 | 8 | 0 | 0 |
| `prompt_34` | review | 44.238 | 1527 | 3469 | 7 | 0 | 1 |
| `prompt_35` | successful | 75.728 | 2650 | 4417 | 9 | 0 | 0 |
| `prompt_36` | successful | 59.420 | 2077 | 3294 | 7 | 0 | 0 |
| `prompt_37` | successful | 55.451 | 1967 | 3303 | 7 | 0 | 0 |
| `prompt_38` | successful | 126.118 | 4338 | 4784 | 9 | 0 | 0 |
| `prompt_39` | review | 182.704 | 6043 | 4311 | 8 | 1 | 2 |
| `prompt_40` | successful | 11.769 | 363 | 3228 | 7 | 0 | 0 |
| `prompt_41` | review | 103.903 | 3473 | 3643 | 7 | 1 | 1 |
| `prompt_42` | review | 50.924 | 1815 | 3890 | 8 | 1 | 0 |
| `prompt_43` | review | 83.093 | 2962 | 4048 | 8 | 1 | 0 |
| `prompt_44` | review | 145.147 | 5027 | 4913 | 9 | 1 | 0 |
| `prompt_45` | successful | 129.492 | 4532 | 3612 | 7 | 0 | 0 |
| `prompt_46` | successful | 184.859 | 6159 | 5012 | 9 | 0 | 0 |
| `prompt_47` | review | 158.832 | 4902 | 4424 | 8 | 0 | 1 |
| `prompt_48` | successful | 84.816 | 2932 | 3788 | 8 | 0 | 0 |
| `prompt_49` | successful | 43.854 | 1514 | 3717 | 8 | 0 | 0 |
| `prompt_50` | successful | 86.673 | 3039 | 4814 | 9 | 0 | 0 |
| `prompt_51` | review | 46.887 | 1667 | 3344 | 7 | 1 | 0 |
| `prompt_52` | review | 71.866 | 2514 | 3488 | 7 | 1 | 0 |
| `prompt_53` | successful | 74.048 | 2689 | 4171 | 8 | 0 | 0 |
| `prompt_54` | successful | 21.003 | 716 | 3261 | 7 | 0 | 0 |
| `prompt_55` | successful | 51.615 | 1921 | 3280 | 7 | 0 | 0 |
| `prompt_56` | review | 147.472 | 5009 | 3916 | 7 | 0 | 1 |
| `prompt_57` | successful | 12.942 | 410 | 3199 | 7 | 0 | 0 |
| `prompt_58` | successful | 36.258 | 1243 | 2934 | 6 | 0 | 0 |
| `prompt_59` | not_generatable | 158.668 | 5494 | 4218 | 7 | 3 | 0 |
| `prompt_60` | review | 228.752 | 7149 | 4803 | 7 | 1 | 0 |
| `prompt_cli_tool` | review | 20.803 | 567 | 2510 | 5 | 0 | 1 |
| `prompt_expenses` | review | 211.179 | 5728 | 10843 | 9 | 4 | 0 |
| `prompt_gui` | review | 114.381 | 3436 | 6609 | 8 | 2 | 0 |
| `prompt_hello_world` | successful | 7.078 | 176 | 2274 | 5 | 0 | 0 |
| `prompt_inventory` | review | 133.682 | 3826 | 8285 | 9 | 1 | 0 |
| `prompt_library_system` | review | 242.984 | 6197 | 19463 | 14 | 4 | 2 |
