# Final Mac chain — 2026-11-26

## Result

**Status: stopped at the acceptance gate.**

The `mac-final4` run completed extraction, sidecar adaptation, deterministic repair, and generation for all 66 projects. Readiness is clean (`0` blockers, `0` open ties, `96` risks). Acceptance is still the blocking gate: the fresh-scenario acceptance sweep did not complete because generated CLI workers hung, and three projects still contain generated stubs. The canonical verifier was therefore not run.

- Run root: `out/validation/runs/mac-final4-20261125`
- Model: `Qwen3-4B-Instruct-2507-Q4_K_M.gguf`, llama-server
- Gate: `scripts/run_bench_acceptance.py` with CLI scenarios regenerated from the current surface

## Extraction

- 66 prompts: **40 successful, 24 review, 2 not_generatable**; the two not-generatable results were resolved by sidecar/repair, not hidden.
- Per-prompt time sum: **5248.332 s**; wall time: **5,249 s** (14:03:21–15:30:50 UTC).
- Tokens: **175,211** generated / **276,247** prompt; **501** model calls.

The two `not_generatable` prompts were `prompt_34` and `prompt_59` (adapter entity spelling/mapping issues). The deterministic repair stage corrected those and brought readiness to zero blockers.

## Sidecar variance and repair

- Review fill: **2.458 s**, exit `0`.
- Deterministic repair: **16.837 s** (initial stage).
- Sidecars copied from the prior/stable runs: **57** files.
- Structural variance versus `kaggle-v8`:
  - commands changed: **38** prompts
  - models changed: **4** prompts
  - services changed: **8** prompts
  - repository interfaces changed: **2** prompts
  - adapter sets changed: **47** prompts
- Final readiness: **0 blockers, 0 open ties, 96 risks**. The variance detail is in `sidecar_variance.json`; the final probe is `final_readiness.txt`.

Generic repairs added during this pass: nested service declarations promoted/dropped, missing read-one and standard repository methods completed, missing CRUD command groups restored, service parameters completed from model/description evidence, CLI option types aligned with model fields, adapter entity names canonicalized, duplicate adapters removed, aggregate mapping returns grouped, and optional validation parameters allowed when unused.

## Generation

- All 66 projects have generated packages (`generated/`), but generation was **hybrid**, not one uninterrupted model pass.
- The local llama-server became pathologically slow on requests above roughly 4K prompt tokens (one request took about 58 minutes for 204 generated tokens). The run was restarted under `caffeinate`; the pathological request still stalled, so `prompt_47` and `prompt_50`–`prompt_66` used reviewed-body sidecars from the green reference after current documents were repaired. This is recorded as variance, not presented as a clean model generation.
- Generation LLM dumps (where present):
  - calls: **32**
  - output tokens: **4,845**
  - prompt tokens: **116,590**
  - decode seconds: **762.948**

### Remaining generated stubs

- `prompt_19`: `validate_task_creation`, `validate_task_update`, `import_tasks_from_json`, `transition_task_status`, `handle_validation_failure`, `get_task_statistics`, `ensure_task_status_transition_valid`, `validate_task_data_integrity`
- `prompt_39`: `get_admin_users`
- `prompt_44`: `getTopSellingProducts`

## Acceptance

The acceptance harness was corrected so its CLI cases are regenerated from the current effective surface; the checked-in CLI fixtures are no longer replayed against a different surface. The fresh sweep still did not finish: some generated CLI subprocesses hang, and the process-group timeout workaround was not enough to complete a clean 66-project sweep in the time available.

For transparency, the older complete run that used the stale checked-in CLI scenarios reported **50 passed / 14 failed / 2 incomplete**; that result is **not** used as the final acceptance result because it tested the wrong CLI surface. The fresh sweep passed the first projects through `prompt_09` before a worker hung.

Because acceptance is a failed gate, `scripts/run_verifier.py`, intent generation, case planning and the final canonical trace were not run.

## Interpretation

The extraction variance is real and now measured: 38 command surfaces, 47 adapter sets, 8 service sets and 4 model sets differ from the green reference. Sidecars and deterministic repairs can make the documents generatable, but they do not make the generated CLI runtime hang-proof. The next generic fix is to bound every generated CLI invocation and every worker subprocess with a process-group timeout, then finish the fresh acceptance sweep before touching the verifier.

## Artifacts

- `out/validation/runs/mac-final4-20261125/summary.json`
- `out/validation/runs/mac-final4-20261125/sidecar_variance.json`
- `out/validation/runs/mac-final4-20261125/final_readiness.txt`
- `out/validation/runs/mac-final4-20261125/chain_metrics.json`
- `out/validation/runs/mac-final4-20261125/acceptance/_scenarios3/` — regenerated fresh CLI scenarios
- `out/validation/runs/mac-final4-20261125/acceptance/` — acceptance artifacts

## Per-prompt extraction

| Prompt | Class | Seconds | Tokens out | Prompt tokens | Calls | Blockers | Ties |
|---|---:|---:|---:|---:|---:|---:|---:|
| `prompt_01` | successful | 7.766 | 163 | 2191 | 5 | 0 | 0 |
| `prompt_02` | successful | 11.433 | 382 | 2274 | 5 | 0 | 0 |
| `prompt_03` | successful | 43.690 | 1457 | 3340 | 7 | 0 | 0 |
| `prompt_04` | review | 43.384 | 1521 | 3840 | 8 | 0 | 1 |
| `prompt_05` | successful | 22.205 | 773 | 3259 | 7 | 0 | 0 |
| `prompt_06` | successful | 23.558 | 822 | 3232 | 7 | 0 | 0 |
| `prompt_07` | successful | 43.807 | 1508 | 3883 | 8 | 0 | 0 |
| `prompt_08` | successful | 21.556 | 762 | 3315 | 7 | 0 | 0 |
| `prompt_09` | review | 33.801 | 1185 | 3392 | 7 | 0 | 2 |
| `prompt_10` | successful | 45.564 | 1613 | 3917 | 8 | 0 | 0 |
| `prompt_11` | review | 77.940 | 2653 | 3996 | 8 | 0 | 1 |
| `prompt_12` | successful | 75.523 | 2633 | 3860 | 8 | 0 | 0 |
| `prompt_13` | successful | 84.978 | 3140 | 4526 | 9 | 0 | 0 |
| `prompt_14` | successful | 50.577 | 1749 | 4058 | 8 | 0 | 0 |
| `prompt_15` | successful | 19.955 | 699 | 3225 | 7 | 0 | 0 |
| `prompt_16` | successful | 48.552 | 1772 | 4418 | 9 | 0 | 0 |
| `prompt_17` | successful | 53.555 | 1953 | 3873 | 8 | 0 | 0 |
| `prompt_18` | successful | 77.842 | 2689 | 4620 | 9 | 0 | 0 |
| `prompt_19` | review | 151.840 | 4970 | 3334 | 7 | 0 | 3 |
| `prompt_20` | successful | 87.179 | 3043 | 3361 | 7 | 0 | 0 |
| `prompt_21` | successful | 70.837 | 2507 | 3408 | 7 | 0 | 0 |
| `prompt_22` | successful | 158.024 | 4418 | 4924 | 9 | 0 | 0 |
| `prompt_23` | review | 126.377 | 3974 | 3534 | 7 | 0 | 1 |
| `prompt_24` | successful | 78.185 | 2646 | 4102 | 8 | 0 | 0 |
| `prompt_25` | review | 43.953 | 1574 | 3264 | 7 | 0 | 1 |
| `prompt_26` | review | 98.697 | 3386 | 3630 | 7 | 0 | 1 |
| `prompt_27` | successful | 205.696 | 7019 | 4261 | 8 | 0 | 0 |
| `prompt_28` | review | 81.843 | 2845 | 3654 | 7 | 2 | 1 |
| `prompt_29` | successful | 63.943 | 2120 | 3437 | 7 | 0 | 0 |
| `prompt_30` | successful | 16.676 | 567 | 3253 | 7 | 0 | 0 |
| `prompt_31` | successful | 37.646 | 1307 | 3348 | 7 | 0 | 0 |
| `prompt_32` | successful | 30.056 | 958 | 3351 | 7 | 0 | 0 |
| `prompt_33` | successful | 73.614 | 2571 | 4140 | 8 | 0 | 0 |
| `prompt_34` | not_generatable | 48.546 | 1622 | 4230 | 8 | 2 | 1 |
| `prompt_35` | review | 66.738 | 2325 | 4418 | 9 | 1 | 0 |
| `prompt_36` | successful | 57.082 | 2077 | 3294 | 7 | 0 | 0 |
| `prompt_37` | successful | 56.795 | 1967 | 3303 | 7 | 0 | 0 |
| `prompt_38` | successful | 123.449 | 4338 | 4784 | 9 | 0 | 0 |
| `prompt_39` | review | 180.032 | 6043 | 4311 | 8 | 1 | 2 |
| `prompt_40` | successful | 12.110 | 363 | 3228 | 7 | 0 | 0 |
| `prompt_41` | review | 101.149 | 3473 | 3643 | 7 | 1 | 1 |
| `prompt_42` | review | 52.266 | 1815 | 3890 | 8 | 1 | 0 |
| `prompt_43` | review | 87.674 | 2962 | 4048 | 8 | 1 | 0 |
| `prompt_44` | review | 153.714 | 5027 | 4913 | 9 | 1 | 0 |
| `prompt_45` | successful | 135.018 | 4532 | 3612 | 7 | 0 | 0 |
| `prompt_46` | successful | 182.279 | 6159 | 5012 | 9 | 0 | 0 |
| `prompt_47` | review | 143.124 | 4902 | 4424 | 8 | 0 | 1 |
| `prompt_48` | successful | 80.546 | 2932 | 3788 | 8 | 0 | 0 |
| `prompt_49` | successful | 43.269 | 1514 | 3717 | 8 | 0 | 0 |
| `prompt_50` | successful | 86.721 | 3039 | 4814 | 9 | 0 | 0 |
| `prompt_51` | review | 47.026 | 1667 | 3344 | 7 | 1 | 0 |
| `prompt_52` | review | 71.361 | 2514 | 3488 | 7 | 1 | 0 |
| `prompt_53` | successful | 74.741 | 2689 | 4171 | 8 | 0 | 0 |
| `prompt_54` | successful | 21.565 | 716 | 3261 | 7 | 0 | 0 |
| `prompt_55` | successful | 52.153 | 1921 | 3280 | 7 | 0 | 0 |
| `prompt_56` | review | 144.463 | 5009 | 3916 | 7 | 0 | 1 |
| `prompt_57` | successful | 12.910 | 410 | 3199 | 7 | 0 | 0 |
| `prompt_58` | successful | 35.977 | 1243 | 2934 | 6 | 0 | 0 |
| `prompt_59` | not_generatable | 163.114 | 5494 | 4218 | 7 | 3 | 0 |
| `prompt_60` | review | 218.825 | 7149 | 4803 | 7 | 1 | 0 |
| `prompt_cli_tool` | review | 18.713 | 567 | 2510 | 5 | 0 | 1 |
| `prompt_expenses` | review | 193.520 | 5728 | 10843 | 9 | 6 | 0 |
| `prompt_gui` | review | 111.326 | 3436 | 6609 | 8 | 2 | 0 |
| `prompt_hello_world` | successful | 6.743 | 176 | 2274 | 5 | 0 | 0 |
| `prompt_inventory` | review | 123.888 | 3826 | 8285 | 9 | 1 | 0 |
| `prompt_library_system` | review | 231.243 | 6197 | 19463 | 14 | 4 | 2 |
