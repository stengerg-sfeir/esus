# Validation of the 66-prompt suite

## Current status (2026-11-19)

The current reproducibility job extracts the **60 validation prompts plus the
six initial prompts** (`hello_world`, `cli_tool`, `expenses`, `gui`,
`inventory`, `library_system`).

Latest Kaggle run (`repro66-20261119-105248`, kernel version 8):

- **42 successful / 24 review / 0 failed**
- **3,596 s** total extraction
- **529** timed model calls
- **197,885** output tokens / **292,957** prompt tokens

Local replay from that extraction, using the conservative review sidecars and
the current generator:

- **66/66 generated**
- **66/66 complete acceptance projects**
- **1,023 checks passed**
- **0 failed**
- **0 not applicable**
- **1,382 unit tests passed**

State effects and invalid preconditions are now derived from the confirmed
contracts, so ordinary state transitions no longer need prompt-specific
fixtures. The stored v8 artifact has no `not_applicable` checks.

Unreviewed inferred unique fields are not asserted by the runtime harness:
they are neither required nor forbidden until `review_uniqueness.py` records
a decision. Explicit and confirmed constraints are still checked, and rejected
ones must not be enforced. This removes the old count of inferred-unique
checks (1,073 -> 1,023) rather than hiding a defect.

The checked-in CLI fixtures were regenerated from the effective generated
surface while preserving every non-CLI semantic scenario. A fresh replay of
the stored v8 code now gives **66/66 complete projects, 1,023 passed checks,
0 generated stubs, 0 failures**. The separate requirement trace still reports 37 unmapped,
11 partial and 127 mapped-but-untested clauses; those remain review targets
(item 7b), not proof of semantic coverage.

The acceptance summary also carries a separate `coverage` block produced
by `scripts/requirement_trace.py`. It maps each requirement clause to design
evidence and says whether a check names it; it is not part of the pass/fail
verdict.

## Goal

Run `extract_arch.py` on the 60 prompts in `prompts/validation/` plus the six
initial prompts and measure, per prompt:

- wall-clock time;
- prompt and generated tokens;
- whether the extracted architecture is **successful** (formerly called direct);
- whether it becomes generatable **after human review**;
- whether it is **not generatable**.

The run is extraction-only. Code generation is a separate follow-up so a
failed extraction does not hide its token and timing cost inside a generator
run.

All results must remain reproducible from the prompt text and the recorded
model/server configuration.

## Inputs

- 60 validation prompts: `prompts/validation/prompt_01.txt` … `prompt_60.txt`.
- Six initial prompts: `prompts/initial/prompt_*.txt`.
- Extraction entry point: `extract_arch.py`.
- Model: Qwen3-4B-Instruct-2507-Q4_K_M through `llama-server` at
  `http://127.0.0.1:8080` by default.
- The same extraction flags used by the main reviewed pipeline:
  - `ESUS_COMPONENTS_SPLIT=1`
  - `ESUS_MECHANICAL_SCHEMA=1`
  - `ESUS_MECHANICAL_SERVICES=1`
  - `ESUS_MECHANICAL_ADAPTERS=1`

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

## Current review policy

Extraction still runs unreviewed first. When a local replay is wanted,
`scripts/answer_reviews.py` is deliberately conservative:

- it answers a slot only when the offered candidate set is a singleton;
- it keeps the recorded tie only when the choice is forced; ambiguous ties,
  slots, routes and contracts remain open;
- it never drops an upstream gap or a flag just to make the probe green;
- it does not invent a state value or a free-form precondition.

The remaining questions are the required attended review. Run
`python scripts/review_queue.py OUT_ROOT` to write `review_queue.json` (and
optionally Markdown) with every open question, its source, candidates and
resolver. The review sidecars are `decisions.json`, `method_slots.json`,
`surface_decisions.json`, `method_contracts.json`, `grounding_decisions.json`,
`unique_decisions.json` for confirmed/rejected inferred unique fields,
`unique_policy.json` for grouped decisions at a validation root, and
`flag_decisions.json` for ambiguous method-backed flags. After those decisions
are written, `extract_arch.py --repair` re-applies the deterministic document
and adapter repairs; it makes no model calls and does not answer review
questions.

The v8 replay used evidence-backed decisions for the open cases and added two
state-effect acceptance scenarios, so the final harness has no
`not_applicable` state checks.

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

Result: `successful`, first cold run **17.155 s**, warm repeat **8.477 s**,
**320** generated tokens, **1 639** prompt tokens, 6 timed calls, 0 blockers,
0 ties. This validates the subprocess, summary parser, token parser, and
classification path. It is not a representative sample of the 60-prompt
suite.

## Calibration results (2026-11-12)

The first complete calibration ran on two visible GPUs with one
`llama-server` (`--parallel 2`) and `run_validation.py --concurrency 2`.

| Prompt | Class | Time | Tokens out | Tokens prompt | Observed blocker |
| --- | --- | ---: | ---: | ---: | --- |
| `prompt_01` | successful | 66.6 s | 320 | 1 639 | none |
| `prompt_10` | successful | 126.3 s | 3 281 | 4 406 | none |
| `prompt_20` | review | 172.4 s | 4 775 | 4 597 | 2 open ties |
| `prompt_30` | not generatable | 71.1 s | 2 689 | 2 050 | persistence required, no data models/CRUD, 14 surface questions |
| `prompt_40` | not generatable | 42.1 s | 1 247 | 1 857 | persistence required, no data models/CRUD, 1 surface question |
| `prompt_50` | review | 151.0 s | 3 492 | 3 860 | 1 open tie |
| `prompt_56` | review | 511.4 s | 13 257 | 7 117 | 3 method contracts |
| `prompt_60` | review | 481.8 s | 23 758 | 10 068 | 1 pattern slot + 5 contracts |
| **Total** | 2 successful / 4 review / 2 blocked | **27m 03s** | **52 819** | **35 594** | 96 timed calls |

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

The current 66-prompt kernel is
`gillesstenger/esus-reproducibility-66-prompts`; its sources are
`gillesstenger/esus-code-bundle` and `gillesstenger/qwen3-4b-instruct`. The
runner's parser, classifier, and extraction environment are covered by
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
  `successful`, 17.155 s cold / 8.477 s warm, 320 output / 1 639 prompt tokens.
- Added the Kaggle notebook, kernel metadata, dataset/push instructions, and
  parser/classifier unit tests.
- Kaggle credentials are configured (`kaggle 2.2.4`).
- Uploaded `gillesstenger/esus-code-bundle` (a zip containing
  `esus-code.bundle`) and `gillesstenger/qwen3-4b-instruct`; pushed
  `gillesstenger/esus-validation-60-prompts`.
- The notebook now extracts the code archive, uses official CUDA prebuilts
  with a CPU fallback, starts one server with two decode slots, runs the
  concurrent prompt runner, and archives the single run directory.
- Completed the 8-prompt calibration: 2 successful, 4 review, 2 not generatable;
  total 27m 03s and 52,819 output / 35,594 prompt tokens. The two blocked
  prompts both extract zero data models while declaring persistence required.
- `ESUS_COMPONENTS_SPLIT=1` is now ignored when a prompt states no command
  lines; the single components call replaces the plan plus one call per group.
  On `prompt_60` that took extraction from **651.0 s / 24,499 tokens / 23
  steps** to **278.9 s / 10,438 tokens / 8 steps**.  See `doc/speed.md`.
- `ESUS_MECHANICAL_ADAPTERS=1` is now the default in the extraction pipeline
  (set `ESUS_MECHANICAL_ADAPTERS=0` to force the model).  It derives the
  interaction adapters from the command surface, service signatures and data
  model.  With split off it took `prompt_60` to **175.3 s / 7,149 tokens / 7
  steps** with the same readiness result.  The dependent-entity completion adds
  the missing `OrderItemRepository` and its `get_order_items_by_order_id` query;
  with the preserved review answers the generated program passes the 60
  acceptance suite **10/10**.
- `main.py` also enables `ESUS_DOMAIN_TRIAGE` by default.  On a one-letter
  `Y/N/U` answer, `N` skips extraction and goes straight to the one-file
  `app.py` fallback.  On 66 initial+validation prompts the answer was
  **62 Y / 4 N / 0 U**, with **0 false N**, for **15.2 s total** triage cost.
  The six initial prompts moved from **1,333 s / 35,430 tokens** to
  **691 s / 21,643 tokens** with the same acceptance results.

### 2026-11-13/14 — generic repair pass

The first full run (`kaggle-20261113-121941`, label `direct`) produced
**28 direct / 22 review / 10 not generatable** in **6,448.1 s**, with
**212,199** output and **255,764** prompt tokens. Triage of the 10 blocked
prompts is in `doc/validation-triage.md`.

Generic repairs were then added and the full suite was rerun as
`kaggle-20261113-170925` with the `successful` label:

| Class | Prompts |
| --- | ---: |
| `successful` | 32 |
| `review` | 27 |
| `not_generatable` | 1 |

**Measured total:** **6,847.0 s**, **218,965** output tokens, **260,879**
prompt tokens, **502** timed calls.

The single hard blocker was `prompt_03` (`persistence_ports.json` was written
as `null` after the persistence step was skipped). The skip path now removes
the document key, and the adapter-side unify pass only runs when a ports
object exists; the archived output re-probes as **review** with one unanswered
method contract. Adjusted final classification: **32 successful / 28 review /
0 not generatable**.

Repairs introduced or exercised in this pass:

- persistence `required=true, technology=none` becomes not required;
- unknown raised errors are registered, or an ungrounded validation raise is
  dropped;
- `<Entity>_primary_key` foreign keys are renamed to `<entity>_id`;
- plain create methods receive required non-null model fields;
- adapter transforms agree with boolean/enum target types;
- the false entity target for a `dict` payload on a `-> None` method is gone;
- merged repository/service method lists are deduplicated;
- search/export/import actions get a capability method and adapter
  (export/import get a service; prose import also gets the missing CLI leaf);
- an empty domain model is inferred from the application noun (`prompt_40`:
  `Order`), with standard CRUD and persistence enabled;
- CSV export works without a date field or explicit path, and JSON export is
  mechanical.

The validation suite now has no structural blocker after the `prompt_03`
skip-path fix. Remaining results are review questions (ties, open contracts,
ignored options), not generation failures. The targeted local reruns for the
formerly blocked prompts were: `prompt_03` review, `prompt_13` successful,
`prompt_18` successful, `prompt_19` review, `prompt_26` review,
`prompt_32` successful, `prompt_34` review, `prompt_40` successful,
`prompt_41` successful, `prompt_60` review.

## Bench generation (2026-11-16)

The final Kaggle output was downloaded to `out/validation/bench/`. This
paragraph records the older 2026-11-16 bench policy, not the current
`answer_reviews.py`: that historical run kept the recorded classifier, kept
both duplicate surface nodes, took the first enumerated slot, kept proposed
contracts, skipped optional checks, and kept grounding evidence. Dead flags
whose upstream relationship was absent were recorded as explicit `drop-flag`
surface decisions so the generated program remained runnable. The current
policy above leaves ambiguous decisions open instead.

All 60 prompt directories now probe with **zero blockers** and have a
generated package. `generator.py` reports:

- **777** methods;
- **63** bodies written provisionally by the model;
- **0** documented stubs remaining.

`python3 -m compileall out/validation/bench` is clean. The only CLI smoke
exception is the degenerate `prompt_02` calculator, whose `app.py` expects its
three runtime arguments rather than `--help`. Per-prompt counts are in
`out/validation/bench/summary.json`.

The generic runtime harness is in `tests/runtime/worker.py` and
`scripts/run_bench_acceptance.py`. It runs one fresh interpreter per prompt,
imports the generated package, checks every CLI leaf's `--help`, validates the
schema and store round-trips, exercises CRUD and unique/foreign-key
constraints, executes scalar-effect method contracts through the generated
service/repository, and runs **268** data-driven CLI and semantic scenarios.
CLI scenarios are generated from the surface the generator actually emits;
each runs in a fresh SQLite database with the foreign keys it needs seeded.

Final result on `out/validation/bench` (historical 2026-11-16 archive):

- **60 / 60 prompts passed**;
- **1002 checks passed**, **0 failed**, **0 skipped**;
- `python3 -m compileall out/validation/bench` is clean.

The current 66-project v8 result above supersedes these counts: **56/66
complete, 1,023 passed checks, 0 generated stubs, 0 failures**. The generic harness now includes
state-effect scenarios for cancellation and return, so the older
`not_applicable` checks are no longer skipped.

The same harness now discovers the six named initial projects under
`out/initial/esus_bench/`; the runner is no longer limited to `prompt_*`
directories. Final result on that archive:

- **6 / 6 projects passed**;
- **124 checks passed**, **0 failed**, **0 skipped**;
- **35** initial CLI scenarios alongside the **268** validation scenarios;
- `python3 -m compileall out/initial/esus_bench` is clean.

Applying the harness to the initial archive exposed generic rules that are now
part of it: multi-word component names (`category add`) become separate argv
tokens; nullable state columns start NULL unless a precondition asks for a
value; a forbidden `field is not None` seeds NULL; toggle effects
(`is_active = not is_active`) are compared against the pre-call value; update
fixtures identify standard CRUD rows by primary key and leave composite-unique
filters untouched; numeric comparison invariants produce distinct fixtures;
`--category` resolves to the `category_id` foreign key; grounding decisions
filter stale contracts; and bare file placeholders are materialised in a
temporary directory instead of the working tree.

The harness is deliberately data-driven and never edits generated code. The
scenario pass exposed and drove these generic fixes:

- DTO/mapping creates group their fields into the documented request object
  instead of passing the last flag as a scalar;
- an aggregate create that cannot consume its CLI fields falls back to the
  entity's plain `create`, with the stale line flags removed;
- delete operations require only their key, while non-key adapter fields stay
  optional;
- reviewed bodies cannot invent a state guard the method contract never
  declared;
- ISO date transforms accept full datetimes as well as dates;
- file/path arguments receive a real temporary CSV for import commands;
- fixture seeding gives unique columns fresh values, and repository fixtures
  respect stock/quantity invariants.

The scenario pass also exercised generic collection and record-create rules:
`place_order` now creates one `OrderItem` per collection element, and a
`record_*` repository method is a create with a stock effect. The `prompt_60`
stock gap is covered by an inferred stock contract and its scenario passes.

The generator was also hardened to defer annotations (undefined type names
such as `UUID` no longer abort import), normalize generic `List<T>`/`Map<K,V>`
spellings from extraction into Python annotations, and degrade gracefully when
a prompt module is truncated. A `null` persistence document and merged-method
duplicates are removed by the generic repair path.

The remaining stubs were removed with domain-neutral rules:

- a `*Repository` contract is never emitted as a service class;
- contract writes are recognised through `store.update(..., patch)`, not by a
  method name;
- a create is counted per repository/entity, so creating an order line beside
  its order is not a duplicate order;
- a capability action may only attach to a service that owns its entity, or be
  removed for review rather than attached to the wrong service;
- state transitions from `from X to Y` or `status is updated to Y` become
  reviewed state effects and preconditions, including `Already<State>Error`
  checks.
