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

## Kaggle plan

The Kaggle key is not yet available, so the upload/push steps are prepared but
not executed.

### 1. Upload the code and model

Two private Kaggle datasets are needed:

1. **ESUS code**: this repository snapshot including `extract_arch.py`,
   `kernel/`, `prompts/validation/`, and `scripts/run_validation.py`.
2. **Qwen model**: `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` (about 2.3 GB).

The notebook mounts them at:

```text
/kaggle/input/esus-code/
/kaggle/input/qwen3-4b-instruct/
```

If Kaggle internet is enabled, the model can instead be downloaded in the
notebook; a dataset avoids relying on a third-party URL.

### 2. Build the runtime

The notebook must provide a `llama-server` binary. Preferred path:

```sh
git clone --depth 1 https://github.com/ggml-org/llama.cpp
cmake -S llama.cpp -B llama.cpp/build -DGGML_CUDA=ON -DLLAMA_CURL=OFF
cmake --build llama.cpp/build --config Release -j2
```

Then start the model with the same context/slot settings as ESUS:

```sh
llama-server -m /kaggle/input/qwen3-4b-instruct/Qwen3-4B-Instruct-2507-Q4_K_M.gguf \
  -c 16384 -ngl 99 -fa on --port 8080 -np 1
```

The notebook waits for `GET /health` before running the validation.

### 3. Run with checkpointing

Kaggle sessions are time-limited, and a 60-prompt extraction run can exceed a
single session. The runner already supports resume:

```sh
python3 scripts/run_validation.py \
  --prompts prompts/validation \
  --out out/validation/runs \
  --run-id kaggle-<date> \
  --server-url http://127.0.0.1:8080
```

A directory with `metrics.json` is skipped unless `--force` is passed. The
notebook should run in batches if necessary:

```sh
--only prompt_01,prompt_02,...,prompt_10
```

or use `--limit` for a first calibration batch.

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

The metadata uses placeholders for the Kaggle username and dataset IDs until
the API key and account name are supplied. The runner's parser and classifier
are covered by `tests/test_validation_runner.py`.

## Open items

- [ ] Receive Kaggle API credentials and username.
- [ ] Create/upload the code and model datasets.
- [ ] Replace placeholder dataset IDs and kernel owner in `kaggle/`.
- [ ] Push the kernel with `kaggle kernels push`.
- [ ] Run a 3–5 prompt calibration batch inside Kaggle.
- [ ] Estimate the full 60-prompt runtime and decide whether to split it.
- [ ] Run all 60 prompts.
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
- Kaggle CLI is installed (`kaggle 2.2.4`) but credentials are not configured
  yet; upload and kernel push are intentionally blocked on the API key.
