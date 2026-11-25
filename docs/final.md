# Final Mac chain — 2026-11-25

## Result

**Status: stopped at the readiness gate.**

The extraction and sidecar/repair phase completed. The chain did **not** run
generation, acceptance or verification because the readiness gate found
non-generatable projects.

- Run root: `out/validation/runs/mac-final-20261125`
- Model: `Qwen3-4B-Instruct-2507-Q4_K_M.gguf`, llama-server, 16,384 context, 1 slot
- Pipeline: `extract_arch.py` via `scripts/run_validation.py`, then sidecar reuse/fill and `--repair`, then `probe_readiness.py`

## Extraction

- Prompts: **66** (60 validation + 6 initial)
- Classification: **40 successful**, **26 review**, **0 failed / not generatable**
- Sum of per-prompt extraction time: **5778.676 s** (96.3 min)
- Generated tokens: **198,616**
- Prompt tokens: **292,261**
- Timed model calls: **527**

The first extraction process stopped externally after `prompt_46` without a
Python traceback or summary. It was resumed from the checkpoint with the same
run id; the resumed pass completed `prompt_47`–`prompt_66` and produced the
66-prompt summary. The time above sums the per-prompt records; wall-clock
includes the interruption.

## Sidecar fill and repair

- Reused review sidecars from `out/validation/kaggle-v8` where present.
- `answer_reviews.py`: **2.518 s**, exit `0`.
- Deterministic `extract_arch.py --repair`: **19.029 s**.
- Readiness probe: **2.813 s**, exit `1`.
- Total measured extraction + fill/repair/readiness: **5803.036 s** (96.7 min).

## Readiness blockers

The readiness gate reported **20 generator blockers**, **108 consistency
risks** and **19 open ties**. The blockers are:

| Prompt | Blocker |
|---|---|
| `prompt_01` | [empty_section] persistence_ports.entity_mappings is empty |
| `prompt_01` | [empty_section] persistence_ports.repositories is empty |
| `prompt_02` | [empty_section] persistence_ports.entity_mappings is empty |
| `prompt_02` | [empty_section] persistence_ports.repositories is empty |
| `prompt_03` | [empty_section] persistence_ports.entity_mappings is empty |
| `prompt_03` | [empty_section] persistence_ports.repositories is empty |
| `prompt_39` | [open_human_review] 1 unanswered pattern slots; run the attended review before generation |
| `prompt_41` | [open_human_review] 1 unanswered pattern slots; run the attended review before generation |
| `prompt_42` | [open_human_review] 1 unanswered pattern slots; run the attended review before generation |
| `prompt_43` | [open_human_review] 1 unanswered pattern slots; run the attended review before generation |
| `prompt_44` | [open_human_review] 1 unanswered pattern slots; run the attended review before generation |
| `prompt_45` | [open_human_review] 1 unanswered method contracts; run the attended review before generation |
| `prompt_52` | [open_human_review] 1 unanswered pattern slots; run the attended review before generation |
| `prompt_58` | [empty_section] persistence_ports.entity_mappings is empty |
| `prompt_58` | [empty_section] persistence_ports.repositories is empty |
| `prompt_cli_tool` | [empty_section] persistence_ports.entity_mappings is empty |
| `prompt_cli_tool` | [empty_section] persistence_ports.repositories is empty |
| `prompt_gui` | [open_human_review] 1 unanswered pattern slots; run the attended review before generation |
| `prompt_hello_world` | [empty_section] persistence_ports.entity_mappings is empty |
| `prompt_hello_world` | [empty_section] persistence_ports.repositories is empty |

Blocked prompts with empty persistence sections are `prompt_01`, `prompt_02`,
`prompt_03`, `prompt_58`, `prompt_cli_tool` and `prompt_hello_world`.
Unanswered pattern slots/contracts account for the remaining blockers.

## Not run

- generation
- acceptance
- prompt-derived verifier
- final acceptance/trace

## Per-prompt extraction

| Prompt | Class | Seconds | Tokens out | Prompt tokens | Calls | Blockers | Ties |
|---|---:|---:|---:|---:|---:|---:|---:|
| `prompt_01` | successful | 9.431 | 163 | 2191 | 5 | 0 | 0 |
| `prompt_02` | successful | 11.895 | 382 | 2274 | 5 | 0 | 0 |
| `prompt_03` | successful | 49.922 | 1671 | 3919 | 8 | 0 | 0 |
| `prompt_04` | review | 47.134 | 1726 | 4303 | 9 | 0 | 1 |
| `prompt_05` | successful | 40.444 | 1512 | 3768 | 8 | 0 | 0 |
| `prompt_06` | successful | 50.03 | 1820 | 3751 | 8 | 0 | 0 |
| `prompt_07` | successful | 31.132 | 1108 | 3874 | 8 | 0 | 0 |
| `prompt_08` | successful | 45.478 | 1631 | 3845 | 8 | 0 | 0 |
| `prompt_09` | review | 55.517 | 2016 | 3932 | 8 | 0 | 2 |
| `prompt_10` | successful | 33.964 | 1211 | 3908 | 8 | 0 | 0 |
| `prompt_11` | review | 73.912 | 2653 | 3996 | 8 | 0 | 1 |
| `prompt_12` | successful | 72.309 | 2633 | 3860 | 8 | 0 | 0 |
| `prompt_13` | successful | 88.171 | 3140 | 4599 | 9 | 0 | 0 |
| `prompt_14` | review | 41.396 | 1452 | 4047 | 8 | 1 | 0 |
| `prompt_15` | successful | 44.503 | 1620 | 3735 | 8 | 0 | 0 |
| `prompt_16` | successful | 60.461 | 2240 | 4364 | 9 | 0 | 0 |
| `prompt_17` | successful | 52.907 | 1953 | 3873 | 8 | 0 | 0 |
| `prompt_18` | successful | 97.873 | 3428 | 4750 | 9 | 0 | 0 |
| `prompt_19` | review | 197.629 | 6624 | 5096 | 9 | 0 | 3 |
| `prompt_20` | successful | 129.335 | 4452 | 4782 | 9 | 0 | 0 |
| `prompt_21` | successful | 104.346 | 3650 | 4092 | 8 | 0 | 0 |
| `prompt_22` | successful | 134.084 | 4627 | 4962 | 9 | 0 | 0 |
| `prompt_23` | review | 164.128 | 5648 | 4368 | 8 | 0 | 1 |
| `prompt_24` | successful | 76.927 | 2646 | 4102 | 8 | 0 | 0 |
| `prompt_25` | review | 60.933 | 2198 | 3859 | 8 | 0 | 1 |
| `prompt_26` | review | 94.409 | 3316 | 3627 | 7 | 0 | 1 |
| `prompt_27` | successful | 200.944 | 7019 | 4261 | 8 | 0 | 0 |
| `prompt_28` | review | 78.937 | 2845 | 3654 | 7 | 0 | 1 |
| `prompt_29` | successful | 63.161 | 2120 | 3437 | 7 | 0 | 0 |
| `prompt_30` | successful | 23.108 | 786 | 3731 | 8 | 0 | 0 |
| `prompt_31` | successful | 54.469 | 1985 | 3874 | 8 | 0 | 0 |
| `prompt_32` | successful | 29.472 | 958 | 3351 | 7 | 0 | 0 |
| `prompt_33` | successful | 98.1 | 3490 | 4105 | 8 | 0 | 0 |
| `prompt_34` | review | 43.735 | 1527 | 3469 | 7 | 0 | 1 |
| `prompt_35` | review | 66.384 | 2325 | 4418 | 9 | 1 | 0 |
| `prompt_36` | successful | 80.699 | 2935 | 3890 | 8 | 0 | 0 |
| `prompt_37` | successful | 58.349 | 2067 | 3947 | 8 | 0 | 0 |
| `prompt_38` | successful | 124.145 | 4338 | 4784 | 9 | 0 | 0 |
| `prompt_39` | review | 177.771 | 6189 | 5069 | 9 | 1 | 2 |
| `prompt_40` | successful | 24.754 | 859 | 3725 | 8 | 0 | 0 |
| `prompt_41` | review | 138.307 | 4864 | 4368 | 8 | 1 | 1 |
| `prompt_42` | review | 51.483 | 1815 | 3890 | 8 | 1 | 0 |
| `prompt_43` | review | 84.312 | 2962 | 4048 | 8 | 1 | 0 |
| `prompt_44` | review | 146.661 | 5027 | 4913 | 9 | 1 | 0 |
| `prompt_45` | review | 121.466 | 4199 | 3606 | 7 | 1 | 0 |
| `prompt_46` | successful | 177.259 | 6159 | 5012 | 9 | 0 | 0 |
| `prompt_47` | review | 228.202 | 7681 | 4332 | 8 | 0 | 1 |
| `prompt_48` | successful | 85.576 | 2932 | 3788 | 8 | 0 | 0 |
| `prompt_49` | successful | 41.696 | 1506 | 3706 | 8 | 0 | 0 |
| `prompt_50` | successful | 89.081 | 3246 | 4890 | 9 | 0 | 0 |
| `prompt_51` | successful | 75.366 | 2708 | 3981 | 8 | 0 | 0 |
| `prompt_52` | review | 84.673 | 3099 | 4271 | 8 | 1 | 0 |
| `prompt_53` | successful | 100.489 | 3602 | 4107 | 8 | 0 | 0 |
| `prompt_54` | successful | 38.996 | 1399 | 3769 | 8 | 0 | 0 |
| `prompt_55` | successful | 76.514 | 2885 | 4475 | 9 | 0 | 0 |
| `prompt_56` | review | 141.512 | 5009 | 3916 | 7 | 0 | 1 |
| `prompt_57` | successful | 21.821 | 788 | 3677 | 8 | 0 | 0 |
| `prompt_58` | successful | 34.525 | 1243 | 2934 | 6 | 0 | 0 |
| `prompt_59` | successful | 155.74 | 5494 | 4218 | 7 | 0 | 0 |
| `prompt_60` | review | 212.713 | 7149 | 4803 | 7 | 1 | 0 |
| `prompt_cli_tool` | review | 19.15 | 567 | 2510 | 5 | 0 | 1 |
| `prompt_expenses` | review | 188.931 | 5728 | 10843 | 9 | 4 | 0 |
| `prompt_gui` | review | 112.055 | 3436 | 6609 | 8 | 2 | 0 |
| `prompt_hello_world` | successful | 6.468 | 176 | 2274 | 5 | 0 | 0 |
| `prompt_inventory` | review | 125.221 | 3826 | 8285 | 9 | 1 | 0 |
| `prompt_library_system` | review | 228.161 | 6153 | 19444 | 14 | 4 | 2 |

## Interpretation

The complete chain is blocked by review/readiness, not by an extraction crash.
The sidecars copied from the previous stable run do not cover all new
extraction outputs; the next step is to resolve the listed pattern slots,
method contracts and empty persistence sections, rerun `--repair`, and then
restart from the readiness gate. Generation, acceptance and verification
were intentionally not attempted.

The raw artifacts are in the run root. The machine-readable gate metrics are
at `out/validation/runs/mac-final-20261125/chain_metrics.json`.
