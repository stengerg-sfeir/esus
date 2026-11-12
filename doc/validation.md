# Validation of the 60-prompt suite

## Goal

Run `extract_arch.py` on the 60 prompts in `prompts/validation/` and measure,
per prompt:

- wall-clock time;
- prompt and generated tokens;
- whether the extracted architecture is **directly generatable**;
- whether it becomes generatable **after human review**;
- whether it is **not generatable**.

The run is extraction-only. Code generation is a separate follow-up so a
failed extraction does not hide its token and timing cost inside a generator
run.

All results must remain reproducible from the prompt text and the recorded
model/server configuration.

## Inputs

- 60 prompts: `prompts/validation/prompt_01.txt` … `prompt_60.txt`.
- Extraction entry point: `extract_arch.py`.
- Model: Qwen3-4B-Instruct-2507-Q4_K_M through `llama-server` at
  `http://127.0.0.1:8080` by default.
- The same extraction flags used by the main reviewed pipeline:
  - `ESUS_COMPONENTS_SPLIT=1`
  - `ESUS_MECHANICAL_SCHEMA=1`
  - `ESUS_MECHANICAL_SERVICES=1`

Each prompt runs with `--no-chat --quiet`; review is not answered during
extraction because the experiment needs the **unreviewed** readiness state
first, followed by a classification of what review would be needed.

## Classification

The classifier is deliberately conservative and auditable. Each result keeps
the raw `GENERATABLE` verdict, blocker count, tie count, and rule names.

### Directly generatable

The extraction summary says:

```text
GENERATABLE: YES
blockers: 0, open tie(s): 0
```

No human decision is needed before `generator.py` can run. The summary may
still say `UNREVIEWED`; that is recorded as a provenance note, not as a
review requirement.

### Generatable after review

The extraction does not pass yet, but every blocker is one the existing review
scripts can resolve:

- `open_human_review`;
- `ignored_cli_option` (surface route/drop review);
- open ties, when no hard blocker remains.

This classification is provisional until the review is actually run for that
prompt. The validation report keeps the review rule names so a reviewer can
see exactly what was assumed.

### Not generatable

Any crash, timeout, or blocker outside the reviewable set. Examples include a
missing required surface, contradictory documents, an unmappable adapter, or
an unregistered error. These are not counted as “just review” merely because
a human could eventually repair them.

## Metrics

`scripts/run_validation.py` writes one run directory per invocation:

```text
out/validation/runs/<run_id>/
├── manifest.json
├── summary.json
├── summary.csv
└── <prompt>/
    ├── metrics.json
    ├── extract.out
    ├── extract.err
    ├── run.log
    └── extracted documents ...
```

Token counts are parsed from the extraction timing lines:

- `tokens_out`: generated tokens;
- `tokens_prompt`: prompt/context tokens;
- `calls`: timed model calls;
- `decode_seconds`: recovered from the logged decode rate.

`summary.csv` is the primary table for the experiment. `summary.json` keeps
the full per-prompt records and manifest.

## Local smoke run

The runner has been exercised on the first validation prompt with the local
Qwen server:

```sh
python3.12 scripts/run_validation.py --only prompt_01 --run-id smoke
```

Result: `direct`, first cold run **17.155 s**, warm repeat **8.477 s**,
**320** generated tokens, **1 639** prompt tokens, 6 timed calls, 0 blockers,
0 ties. This validates the subprocess, summary parser, token parser, and
classification path. It is not a representative sample of the 60-prompt
suite.

## Calibration results (2026-11-12)

The first complete calibration ran on two visible GPUs with one
`llama-server` (`--parallel 2`) and `run_validation.py --concurrency 2`.

| Prompt | Class | Time | Tokens out | Tokens prompt | Observed blocker |
| --- | --- | ---: | ---: | ---: | --- |
| `prompt_01` | direct | 66.6 s | 320 | 1 639 | none |
| `prompt_10` | direct | 126.3 s | 3 281 | 4 406 | none |
| `prompt_20` | review | 172.4 s | 4 775 | 4 597 | 2 open ties |
| `prompt_30` | not generatable | 71.1 s | 2 689 | 2 050 | persistence required, no data models/CRUD, 14 surface questions |
| `prompt_40` | not generatable | 42.1 s | 1 247 | 1 857 | persistence required, no data models/CRUD, 1 surface question |
| `prompt_50` | review | 151.0 s | 3 492 | 3 860 | 1 open tie |
| `prompt_56` | review | 511.4 s | 13 257 | 7 117 | 3 method contracts |
| `prompt_60` | review | 481.8 s | 23 758 | 10 068 | 1 pattern slot + 5 contracts |
| **Total** | 2 direct / 4 review / 2 blocked | **27m 03s** | **52 819** | **35 594** | 96 timed calls |

The two long prompts (`prompt_56`, `prompt_60`) dominate: together they take
16m 33s and produce 37 015 output tokens. A full 60-prompt run at this
calibration rate is roughly **3–4 hours** on two slots, before review.
This is a rough estimate because the calibration deliberately includes the
longest prompt.

The kernel log shows each prompt line twice. This is **not a duplicate
extraction**: the run has one command, a global `.validation.lock`, and the
merged summary contains exactly eight unique prompt rows. The duplication is
in Kaggle/Papermill's stdout capture, not in the extraction count.

## Kaggle plan

The code and model datasets are uploaded as private Kaggle datasets, and the
validation kernel is pushed with `kaggle kernels push -p kaggle`.

### 1. Upload the code and model

Two private Kaggle datasets are needed:

1. **ESUS code bundle**: a zip named `esus-code.bundle` containing this
   repository snapshot (`extract_arch.py`, `kernel/`,
   `prompts/validation/`, and `scripts/run_validation.py`), dataset id
   `gillesstenger/esus-code-bundle`.
2. **Qwen model**: `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` (about 2.3 GB),
   dataset id `gillesstenger/qwen3-4b-instruct`.

The notebook finds them under:

```text
/kaggle/input/esus-code-bundle/esus-code.bundle
/kaggle/input/qwen3-4b-instruct/Qwen3-4B-Instruct-2507-Q4_K_M.gguf
```

If Kaggle internet is enabled, the model can instead be downloaded in the
notebook; a dataset avoids relying on a third-party URL.

### 2. Build the runtime

The notebook downloads the official CUDA `llama-server` prebuilt
(`llama-b12110-bin-ubuntu-cuda-12.8-x64`); if that is unavailable it falls
back to a CPU build. It starts **one server with two parallel decode slots**
across all visible GPUs:

```sh
llama-server -m <model> -c 32768 -ngl 99 -fa on --parallel 2 --port 8080
```

The two slots share the loaded model rather than loading it twice. The
notebook waits up to 30 minutes for `GET /health` before running validation.
This startup wait was raised after the first two-server calibration timed out
while loading two copies of the model.

### 3. Run with checkpointing and server slots

Kaggle sessions are time-limited, and a 60-prompt extraction run can exceed a
single session. The notebook runs one extraction process with
`--concurrency 2`, matching the server's two decode slots:

```sh
python3 scripts/run_validation.py \
  --prompts prompts/validation \
  --out out/validation/runs \
  --run-id kaggle-<date> \
  --server-url http://127.0.0.1:8080 \
  --concurrency 2
```

A directory with `metrics.json` is skipped unless `--force` is passed. The
runner records per-prompt wall time and tokens even when both slots are
occupied; these measures include the contention of concurrent decoding.

The calibration set is intentionally varied:

```text
prompt_01, prompt_50, prompt_10, prompt_20,
prompt_30, prompt_40, prompt_56, prompt_60
```

It covers the shortest prompt, CRUD, reporting, architecture, notification,
capacity, atomic stock, and the longest prompt. Only after the calibration
has produced metrics should the full 60-prompt run be started.

`scripts/merge_validation_runs.py` remains available for experiments that
really use separate worker directories, but the normal two-slot path does not
need it.

### 4. Publish results

The notebook writes:

- `summary.json`;
- `summary.csv`;
- per-prompt extraction outputs;
- logs.

These are copied to `/kaggle/working/validation-<run-id>/` and zipped for
download. The run ID and notebook version must be recorded in this document.

### 5. Kaggle kernel metadata

The metadata, notebook and upload instructions live under `kaggle/`:

```text
kaggle/
├── README.md
├── kernel-metadata.json
└── validation.ipynb
```

The metadata now points at `gillesstenger/esus-validation-60-prompts`,
`gillesstenger/esus-code-bundle` and `gillesstenger/qwen3-4b-instruct`. The
runner's parser and classifier are covered by
`tests/test_validation_runner.py`.

## Open items

- [x] Receive Kaggle API credentials and username.
- [x] Create/upload the code and model datasets.
- [x] Replace placeholder dataset IDs and kernel owner in `kaggle/`.
- [x] Push the kernel with `kaggle kernels push`.
- [x] Run an 8-prompt calibration batch inside Kaggle.
- [x] Confirm that the first calibration produced metrics for all 8 prompts.
- [x] Estimate the full 60-prompt runtime under two server slots (3–4 hours).
- [ ] Run all 60 prompts with `--concurrency 2`.
- [ ] Fix the two structural failures: `prompt_30` and `prompt_40` extract
      empty data models while claiming persistence is required (no
      `persistence_ports.json`).
- [ ] Review/run the review scripts on the `review` class and remeasure
      readiness.
- [ ] Compare the counts against the fresh-prompt benchmark in
      `doc/speed.md`.

## Journal

### 2026-11-12

- Confirmed exactly 60 validation prompts.
- Added `scripts/run_validation.py` with subprocess execution, summary
  parsing, token parsing, classification, checkpoint/resume, and CSV/JSON
  output.
- Added the validation runner smoke test; `prompt_01` is classified
  `direct`, 17.155 s cold / 8.477 s warm, 320 output / 1 639 prompt tokens.
- Added the Kaggle notebook, kernel metadata, dataset/push instructions, and
  parser/classifier unit tests.
- Kaggle credentials are configured (`kaggle 2.2.4`).
- Uploaded `gillesstenger/esus-code-bundle` (a zip containing
  `esus-code.bundle`) and `gillesstenger/qwen3-4b-instruct`; pushed
  `gillesstenger/esus-validation-60-prompts`.
- The notebook now extracts the code archive, uses official CUDA prebuilts
  with a CPU fallback, starts one server with two decode slots, runs the
  concurrent prompt runner, and archives the single run directory.
- Completed the 8-prompt calibration: 2 direct, 4 review, 2 not generatable;
  total 27m 03s and 52,819 output / 35,594 prompt tokens. The two blocked
  prompts both extract zero data models while declaring persistence required.
