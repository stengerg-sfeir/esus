# Where ESUS spends its time, and how to make it faster

This page records measurements and the ideas they suggest. Some ideas are implemented and measured; each section says which. Figures marked *measured* come from the server's own timings or a wall-clock run; figures marked *estimate* are guesses to be checked before anyone relies on them.

> **2026-11-13 update.** The table below is the historical 2026-11-10 run. The
> rerun, its corrected latency accounting, the determinism/token/acceptance
> evidence and the scaling and sovereignty caveats are in
> [What the rerun does and does not establish](#what-the-rerun-does-and-does-not-establish-2026-11-13).

## Current 66-prompt status (2026-11-19)

The latest reproducibility run is snapshot `repro66-20261119-105248`
(kernel version 8). It extracts the 60 validation prompts plus the six
initial prompts.

| Run | Outcome | Wall | Calls | Output tokens | Prompt tokens |
| --- | --- | ---: | ---: | ---: | ---: |
| v5 | 39 successful / 27 review / 0 failed | 4,410 s | 529 | 197,975 | 292,980 |
| v6 | 41 / 25 / 0 | 3,843 s | 529 | 197,975 | 292,980 |
| v7 | 41 / 25 / 0 | 4,557 s | 529 | 197,975 | 292,980 |
| **v8** | **42 / 24 / 0** | **3,596 s** | **529** | **197,885** | **292,957** |

The wall differences between runs with the same token counts are server/GPU
variation, not a code-path difference. v8 includes the strict unattended
review policy, post-repair adapter re-derivation, grounded repository
filtering, and mechanical order-placement/stock-check bodies.

Local generation from the v8 extraction took **1,161 s** and produced **66/66**
projects. The generic acceptance harness passed **66/66 projects, 1,023 checks,
0 failed, 0 not applicable**; the two former state-effect gaps
(`OrderService.cancel_order`, `LibraryService.return_book`) now have semantic
scenarios. Unit tests: **1,203 passed**.

The mechanical pass is still the main deterministic lever: `52/66` v5 prompts
were fully derivable from their final documents, while the extraction order
left adapter model calls in `45` prompts. The code now re-derives adapters
after surface repair, but the adapter model-call count still depends on how
much of the surface the first pass exposes. This is the next measured speed
target, not a correctness shortcut.

## ESUS vs direct GPT-6 Luna (2026-11-10)

This is an end-to-end comparison, not a model leaderboard. ESUS ran Qwen3-4B through `llama-server` with one slot; the direct runs were one subagent per prompt using **GPT-6 Luna** through OpenCode Go (`opencode-go/gpt-6-luna`), with the prompt file as the only specification. The direct agents had no ESUS documents or contracts and also wrote their own smoke tests and compliance notes.

Both columns are wall-clock seconds. ESUS times include extraction and generation, plus the one repair pass noted below, but exclude human review time. The review decisions used here were the preserved fixtures at `HEAD:backup/review-inputs-2026-11-10` (the working-tree `backup/` directory has since been removed). The direct times include the agent reading the prompt, writing the application, writing its tests and running them. Hello had run first; the six substantive direct agents then ran concurrently, so the per-prompt times are individual measurements, not a sequential total.

| Prompt | ESUS wall | GPT-6 Luna wall | ESUS / direct | ESUS acceptance | Direct runtime / quality |
| --- | ---: | ---: | ---: | --- | --- |
| Hello world | 14.3 s | 40.1 s | 0.36× | 1/1 | Same acceptance 1/1; runs on Python 3.12 |
| CSV → JSON CLI | 39.8 s* | 78.2 s | 0.51× | 1/1 | Same acceptance 1/1; runs on Python 3.12 |
| Inventory | 228.0 s§ | 172.5 s | 1.32× | 8/8 | 2/2 own tests and CLI smoke; runs on Python 3.12 |
| Wine GUI | 272.3 s | 178.1 s | 1.53× | 11/11 | 3/3 service tests on 3.12; real one-frame launch fails |
| Small business (`60`) | 791.9 s | 198.4 s | 3.99× | 10/10 | 3/3 own tests and CLI lifecycle; runs on Python 3.12 |
| Expenses | 471.3 s† | 222.1 s | 2.12× | 15/16, then 16/16 after repair | 3/3 own tests on 3.14; fails to import on 3.12 |
| Library | 258.9 s§ | 255.3 s | 1.01× | 18/18 | 5/5 own tests on 3.14; fails to import on 3.12 |

A ratio below 1 means ESUS was faster.

\* 24.4 s extraction plus 15.4 s generation after answering the CSV classifier tie.  
† 446.5 s first pass plus one 24.8 s Qwen repair pass that filled the remaining `export_to_csv` stub.  
§ Generation was remeasured after the closed-contract compiler on a clean copy with Qwen: inventory **63.0 s** (was 73 s) and library **26.0 s** (was 67.2 s). Extraction is unchanged: inventory 165 s, library 233 s. Both acceptance suites stayed green.

For scale, the sum of the seven ESUS times is **2,076 s (34m 36s)** and the sum of the seven direct times is **1,145 s (19m 05s)**, a ratio of **1.81×**. From the first direct start to the last direct finish was about **7m 56s**; the six non-hello agents overlapped. The ESUS runs shared one llama.cpp slot and ran one after another.

### What the quality checks showed

- **ESUS was behaviourally complete after review/repair.** All seven ESUS outputs passed their prompt-specific external acceptance suites: 1 + 1 + 8 + 11 + 10 + 16 + 18 = **65 checks**. The only acceptance failure seen in a first pass was the expenses CSV export, which was a documented `NotImplementedError` stub; one Qwen repair pass, with no hand-editing, made it pass.
- **Direct GPT-6 Luna was usually compliant and often concise.** Hello, CSV, inventory and `60` ran on the required Python 3.12 and passed their own tests or a CLI lifecycle check. The inventory and `60` implementations were substantially smaller and easier to inspect than the ESUS outputs.
- **Two direct outputs were not runnable on the required Python 3.12.** The expenses and library packages fail at import with `TypeError: 'function' object is not subscriptable`. A class method named `list` shadows the built-in in the class body, and annotations such as `list[Expense]` are evaluated at class-definition time on 3.12. They pass on Python 3.14, whose deferred annotations avoid the problem. A `from __future__ import annotations` or equivalent would be enough, but the delivered code does not have it.
- **The direct GUI does not reach a real frame here.** Its service tests pass, but Python 3.12 with the installed PyImgui/GLFW raises `OpenGL.error.GLError: err = 1282` inside `GlfwRenderer`. The ESUS GUI ran a real imgui/GLFW frame in the same environment and passed its real-launch check.
- **The direct checks were not the ESUS acceptance suites.** Except for hello and CSV, the direct package layouts are not compatible with the ESUS harnesses, so the table reports their own tests plus targeted CLI/service checks. ESUS's acceptance scripts are external and prompt-specific; the direct subagents wrote their own tests. A larger independent suite now lives in `tests/chatgpt_acceptance/`: on Python 3.14 it reports **90/91** checks, with the real GUI frame as the only failure; on Python 3.12 it reports **58/91** because the expenses and library packages fail at import. That is the clearest quality difference in the run.
- **ESUS pays a large extraction cost on `60`.** The split command surface produced 23 extraction steps and 24,499 generated tokens; the adapter step first hit its 3,584-token ceiling and was retried with a 15,056-token ceiling. That single prompt accounts for 791.9 s of the 2,128 s ESUS total. The direct implementation took 198.4 s and passed its own lifecycle tests.

The practical conclusion is not “one system writes better code”. It is that the direct one-shot path is faster and often surprisingly complete, while ESUS buys its acceptance coverage with much more model work and still needs a repair pass when a provisional body is wrong. A cheap runtime gate for the target Python version and a real GUI launch would have caught every direct failure above before delivery.

Raw runs are on disk but ignored by git: `out/initial/esus_bench/<name>/` and `out/initial/chatgpt_compare/<name>/` hold the six non-60 outputs; the `60` output is under `out/validation/60/esus_bench/60/` and `out/validation/60/chatgpt_compare/60/`. ESUS acceptance commands are the `tests/e2e_*_acceptance.py` scripts with the corresponding directory; the independent direct suites are under `tests/chatgpt_acceptance/`, with `run_all.py` and the Python 3.12 `compat.py` gate.

### Token use

The token accounting is not directly comparable. ESUS counts Qwen's extraction prompts/outputs plus the body-generation prompts/outputs recorded in `llm_stub_answers.json`; the direct counts come from the OpenCode Go session totals and include the agent's reasoning, tool calls, test writing and repeated cached context.

|  | ESUS | GPT-6 Luna |
| --- | ---: | ---: |
| Prompt/input | **340,316** | **1,361,794** buckets |
| — of which cached | 187,166 generation-cache reads | 1,254,273 cache reads |
| Output | **60,980** | **67,057** |
| Reasoning | not reported | **25,173** |
| Reported API cost | local Qwen | **$0.0721** |

ESUS breaks down as 62,618 extraction prompt tokens, 277,698 generation prompt tokens, 52,941 extraction output tokens and 7,308 generation output tokens, plus 731 fallback-app output tokens for hello/CSV. The direct input figure is `input + cache.read + cache.write` from the seven successful sessions; cached reads are still part of the provider's reported context.

## What was measured

This section is the earlier **2026-11-09** library deep-dive; it is not the end-to-end benchmark above.

One clean run of the library prompt (`prompts/initial/prompt_library_system.txt`), on an Apple M1 Pro with 16 GB, Qwen3-4B-Instruct Q4_K_M through `llama-server` with one slot, 16,384 context, the Metal GPU and flash attention. The numbers come from the `print_timing` lines of the server log.

| Phase | Wall time | Measured detail |
| --- | --- | --- |
| Extraction | about 10 min | 172 requests. **Decoding 539 s for 21,013 tokens (about 39 tok/s), 88% of the phase.** Prompt processing 70 s for 26,283 tokens. |
| Generation | about 7.5 min | 26 requests. **Prompt processing 381 s for 131,180 tokens (about 5,000 tokens per request, about 344 tok/s), 86% of the phase.** Decoding 63 s for 2,127 tokens. |

Other measured facts:

- Extraction is mostly a chain: each step needs the documents of the earlier ones. A few independent branches can overlap, but on this machine that measured slower (see [Parallel extraction](#parallel-extraction-opt-in-measured-slower)). Thirteen generation calls produce the documents (`service_contracts` and `persistence_ports` are the largest, 2,400 to 3,100 tokens each, about 70 to 88 s each). About 84 further calls classify methods into patterns.
- The review loop reran five of those calls (components to persistence) in a second round, about 230 s, 39% of the extraction. A run without the review loop (`main.py` by default) took 6m 13s on the expenses prompt.
- Repair asks were rare in the older reference run (2 of the 24 model-written bodies), but the current timing run saw 5 and 75.7 s of first attempts; see [Per-answer timing record](#per-answer-timing-record).
- Runs are deterministic: the same code, model, server flags and context give byte-identical documents, model answers and generated modules (three runs, two after cold server restarts). That makes caching by prompt safe, and it means any change that alters a prompt changes the output once.

## Per-answer timing record

`<out>/llm_stub_answers.json` now records, beside every body answer, `seconds` (wall), `decode_seconds`, `prompt_tokens` and `cached_tokens`; a repaired body also has `first_*` for its first attempt. The `prompt_tokens` figure is the total context offered, so `prompt_tokens - cached_tokens` is the new prefill the server actually processed. The previous dump is moved to `<out>/llm_stub_answers_runs/` before each overwrite, so raw answers from earlier runs are retained.

The first measurements with the 2 GiB/no-spec server:

- **Expenses:** 11 bodies plus 2 repair asks, 111.3 s wall. 51.9k prompt tokens offered, 38.7k served from cache (75%); 51.2 s decoding.
- **Library:** 24 bodies, 303.2 s wall. 154.1k prompt tokens offered, 110.8k from cache (72%); 68.6 s decoding. The other ~224 s is prompt processing and per-request overhead.
- **Library repairs are now material:** 5 of 24 bodies needed one, their first attempts cost 75.7 s, and those bodies total 98.9 s of the 303 s pass. Reducing those repair asks is a measured target.

With the current launch script (no explicit `--cache-ram`), the expenses prompt took **124.3 s cold** and **108.1 s warm**, both passing 13 of 13 checks. That is about 3 s faster than the earlier 2 GiB warm run; the difference is small enough to be close to normal timing variation.

`scripts/dump_body_prompts.py <out>` reconstructs the exact body prompts by replaying the body sequence without a model, pairs them with the raw answers from `llm_stub_answers.json`, and writes `<out>/llm_stub_prompts.md` and `.json`. It reports whether the replayed module text matches the generated files. `scripts/dump_extraction_prompts.py <out>` writes the per-step extraction prompts and archived document answers to `<out>/extraction_prompts.md` and `.json`; it marks retries and review reruns, and says where a later deterministic repair makes the archive differ from the historical request.

## The two phases need different fixes

**Extraction is decode-bound.** The model writes about 21,000 tokens at a fixed rate, and everything else is small. Only generating fewer tokens, or generating them faster, helps.

**Generation is prompt-bound.** Each body prompt re-sends about 5,000 tokens (the rules, the requirements, the module text and the API reference), and decoding the body itself is cheap. Reusing work across requests helps far more here than a faster decoder.

## Ideas, in the order I would try them

1. **Put the shared part of the body prompt first.** **Implemented and measured.** `stub_prompt` now puts the method-specific rules, method name, contract and repair block after the shared rules, references, API, requirements and module text. On the expenses prompt the real body prompts are about 3.8k tokens: before the change a prompt reused only 88 cached tokens and spent about 9.4 s on prefill; after it, the next body reused about 3.6k tokens and spent about 0.42 s. A full regeneration of the expenses output dropped from about 4 minutes to about 2 minutes and still passes 13 of 13 acceptance checks. A from-scratch library generation with the same prompt order took 5m48s for the whole generation pass and passed 17 of 17 checks, against the earlier measured generation phase of about 7.5 minutes. The output changed once, and both acceptance tests were rerun.
2. **Cache every model call by its prompt.** Not implemented. Key a stored answer by the model, the server settings, the prompt text and the sampling parameters. An unchanged rerun then takes seconds, and a rerun after a change recomputes only the calls whose prompt changed. It is safe because the same input gives the same output. It does nothing for a first run, but it is what removes the 8 to 15 minute wait from every fix-and-retry loop.
3. **Speculative decoding for extraction.** **Implemented and measured; no gain on this machine.** The draft model loads and works with the grammar sampler (draft acceptance was mostly 72–95% on the extraction steps), but running the 0.6B model beside the 4B model costs more than the accepted tokens save on this memory-bandwidth-bound M1 Pro. One extraction run took 409.5 s of generation against 397.5 s without a draft; a full body-generation pass took 156.8 s against 125.9 s without one. The launch script therefore defaults to `SPEC=0`. It is left as an opt-in experiment; a different draft model, quant or `--spec-draft-n-max` may change the result. The Qwen3-Reranker-0.6B in the models folder is a scoring model and does not qualify.
4. **Run independent extraction steps in parallel (`-np 2`).** **Implemented and measured; slower on this machine.** See [Parallel extraction](#parallel-extraction-opt-in-measured-slower). Overlapping requests divides decode bandwidth instead of adding it, and the largest adapter step becomes slower when it shares the GPU with pattern classification.
5. **Run generation requests in parallel (`-np 2` to `4`).** **Ruled out on this machine.** Decoding on this GPU is limited by memory bandwidth, and each parallel slot needs its own context and cache. The loaded server already uses about 10 GB of the 16 GB machine, so a second slot does not fit; the body prompts would also have to be built from the same base text so the result does not depend on which request finishes first.
6. **Smaller prompt blocks.** Showing only the target class's methods instead of the whole module cuts prompt processing, but the `exact` context was tuned for the small model, so this risks the quality of the bodies.
7. **Generate schema invariants mechanically.** **Implemented as `ESUS_MECHANICAL_SCHEMA=1`; measured small gain.** Step C now asks for business rules only and derives field type, nullability, uniqueness, key, foreign-key, default and numeric-bound facts from `data_models.json`. On expenses the invariant step fell from 611 to 424 generated tokens (15.3 s to 12.6 s) and kept the same 2 blockers; the extra schema entries are skipped by pattern classification. It is opt-in because the document text changes.
8. **Answer ordinary repository CRUD without the classifier.** **Implemented.** A repository method whose name and return shape already agree (`create`, `read_one`, `read_all`, `filter`) is classified by `codegen.plan_method` instead of a two-stage logprobs call. Replaying the expenses classification took 11.8 s for every item and 8.7 s with the deterministic answers, a 3.1 s saving; aggregates, guards and every service method still reach the model.
9. **Rename an entity-targeted adapter field to its model field.** **Implemented.** A DIRECT field now follows the same unique-containment rule as money and lookup fields, but only when the qualifier is not a unit or identity marker (`budget` -> `monthly_budget` is renamed; `amount` -> `amount_cents` is not). On expenses this removed the 258-token adapter retry and one blocker, taking readiness from 4 blockers to 2.
10. **Generate standard service CRUD mechanically.** **Implemented as `ESUS_MECHANICAL_SERVICES=1`; measured on expenses.** The model emits only custom guards, transitions, aggregates, reports and capability methods; standard `create_/read_/read_all_/update_/delete_` wrappers are added from the data model. Existing methods are kept and checked by CRUD role, so a custom `add_expense` covers create. On expenses the contract call fell from 2,251 to 1,078 tokens (about 59 s to 26 s), total extraction from 9,152 to 8,274 tokens, and 239.5 s to 211.5 s with the same 2 blockers. The one extra review tie was `CategoryRepository.read_all` with optional fields: the model claimed an aggregate, was corrected to `FILTER_BY_FIELD`, and sat 0.047 above `READ_ALL`. A `read_all` method with parameters and a collection return is now answered deterministically as `FILTER_BY_FIELD`, so the combined run has 0 open ties. A missing entity service is deliberately **not** invented: adapters may target its repository instead, which the generator already supports.

## Server launch

Use `scripts/start_llama_server.sh`. Its defaults are the measured model, one slot, 16,384 context, six threads, flash attention, 1024-token batch/ubatch and context shifting. `CACHE_RAM` (MiB, default 4096, `0` = llama.cpp's unlimited default) and `KV_UNIFIED` (`on`/`off`, default `on`) are available for experiments; both measured slower on this machine at 16k/32k. Speculative decoding is opt-in because it measured slower:

```bash
./scripts/start_llama_server.sh                 # no draft
SPEC=1 ./scripts/start_llama_server.sh          # speculative decoding
DRAFT=/path/to/Qwen3-0.6B-Q4_K_M.gguf SPEC=1 ./scripts/start_llama_server.sh
```

The draft model is in `~/Documents/models` as `Qwen3-0.6B-Q4_K_M.gguf`. The Qwen3-Reranker-0.6B there is a scoring model and cannot draft.

The cache is bounded so it does not compete with the rest of a 16 GB machine. The model itself is about 2.3 GB and a 16k KV cache adds roughly 1–2 GB; the prompt cache is only reused prefix state.

## What I would not do

- **A smaller model.** Decoding would be faster, but more bodies would be refused by the gates, and every repair ask costs a full prompt. A weaker model on structured JSON also risks the documents themselves.
- **Shorter descriptions in the documents.** The descriptions are about 30% of the characters of the two largest documents (measured on the final JSON: 29% of `service_contracts`, 32% of `persistence_ports`), so shortening them would save a real share of the decoding, but the contract review reads them: "Sets return_date to today, status to 'returned', and increments available copies" is where a contract's effects come from. Shortening them would lose requirements.
- **Looser sampling or fewer tokens in the budget.** It would trade correctness for seconds.

## Open questions for any speed change

- Does it change the output? Any change to a prompt, a catalogue, a check's message or the numerics changes the generated code once. Rerun the acceptance test, and keep `out/library_correct` as the reference for comparison.
- Does it hold on other machines? Timings and floating-point behaviour depend on the hardware and the llama.cpp build.

### Shared extraction prefix (opt-in)

`ESUS_SHARED_CONTEXT=1` moves the requirements into a fixed first system turn
and puts the step-specific instruction in the user turn. Every extraction prompt
then begins with the same **3,225-character** requirements prefix, so the
server can reuse it:

```bash
ESUS_SHARED_CONTEXT=1 python3 main.py prompts/initial/prompt_expenses.txt \
    --model server -o out/expenses_llama_shared
```

Measured on the expenses prompt, same model and temperature:

| Extraction | Baseline | Shared prefix | Change |
| --- | ---: | ---: | ---: |
| llama.cpp wall | 397.4 s | **326.8 s** | **-18%** |
| llama.cpp generated tokens | 13,837 | 11,913 | fewer retries |

The speed gain is real, but the prompt change also changes the documents:
the shared run had 18 readiness blockers (baseline 4). It is therefore **off by
default** until a reviewed shared-context run passes the same end-to-end
acceptance suite. The flag is the experiment; do not treat it as a free cache on
the current prompts.

Re-tested on the seven reference prompts after the mechanical passes
(2026-11-13): the result is worse, not better. Expenses took **358 s / 13,243
tokens** and stopped on a pattern-slot blocker (current: 180 s / 5,730); library
took 208 s / 7,363 with 14 blockers; GUI crashed during extraction; `60` took
172 s / 6,288 but still had two blockers. Only hello and cli_tool pass because
triage sends them to the fallback before extraction. The flag remains off and
the experiment is abandoned.

Blocker counts count report lines, not independent defects, and every run above
is **unreviewed**. The baseline's 4 were three open review questions plus one
wrong adapter field; the shared run's 18 were three review questions, six wrong
adapter fields, and nine CLI options left unconsumed. The 18 is a worse
extraction, not a slower or broken llama.cpp engine, and neither count is an
acceptance score: the reviewed `out/expenses_correct` is the 13/13 reference.

### Mechanical repository completion

The service-contract step no longer has to be trusted to emit every derived
repository.  `kernel/extraction/repository_contracts.py` adds one
`{Entity}Repository` shell for every CRUD entity that step E omitted, with the
required `create`, `read_one`, `read_all`, `update` and `delete` methods.  A
repository the model *did* emit keeps its methods, including custom aggregates.

Step H now runs before pattern matching and adapters, and
`interfaces.merge_repository_methods` copies any custom methods H discovers back
into the matching service contract before those steps see it.

On the shared-context llama.cpp expenses test this took the readiness count from
**18 to 12 blockers**: the two missing repositories and their derived adapter
failures were fixed.  The remaining 12 are review questions plus filter/field
mappings, not missing repositories.  The baseline layout still produces its
previous **4 blockers**.

### Custom repository methods, without regenerating CRUD

Step H now emits only the **custom** repository queries and aggregates.  The
standard CRUD methods come from `repository_contracts.py`; step H contributes
one repository entry per fixed entity with an empty method list when there is
nothing custom to add.  Its grammar allows an empty method list for exactly
this case.

Measured on expenses, with the same model and temperature:

| Extraction | Before this pass | Custom-method pass |
| --- | ---: | ---: |
| Baseline layout, wall | 397.4 s | **373.7 s** |
| Baseline layout, generated tokens | 13,837 | **12,710** |
| Baseline layout, blockers | 4 | **4** |
| Shared layout, wall | 307.5 s | **246.9 s** |
| Shared layout, generated tokens | 10,315 | **9,166** |
| Shared layout, blockers | 20 | **2** |

The shared run now has only review items and one tie left, not missing
repositories or adapter targets.  The baseline layout keeps its previous four
blockers; the speed and token reduction come mostly from not regenerating the
standard repository method set.  The mechanical method signatures also include
the entity fields, so the adapters can map options such as `--month` and
`--amount` instead of leaving them unconsumed.

### Mechanical persistence mappings

The mapping half of step H is now generated by
`kernel/extraction/mappings.py`, not by the model.  It chooses a plural
snake-case table name, the primary key declared by the data model, and indexes
for unique fields, foreign keys, date/datetime fields and common filter fields.

The model still owns custom repository methods.  It sees a repositories-only
grammar, so it cannot spend tokens on table names, primary keys or indexes.

Measured on expenses:

| Extraction | Model-generated mappings | Mechanical mappings |
| --- | ---: | ---: |
| Baseline wall | 373.7 s | **365.0 s** |
| Baseline persistence tokens | 868 | **828** |
| Shared wall | 246.9 s | 252.7 s |
| Shared persistence tokens | 1,068 | **771** |

The shared wall is within run-to-run variation and was slightly worse in this
sample; the token reduction is consistent.  The baseline layout saved about
9 s and 40 persistence tokens.  Blocker counts stayed at 4 for the baseline and
2 for the shared run.

### Split component surface (opt-in)

`ESUS_COMPONENTS_SPLIT=1` first generates the top-level command plan, then one
call per group.  When the requirements contain explicit command lines, the
group grammar now closes both the subcommand names **and the option names** to
those lines.  This removed a real failure: Qwen had abbreviated
`--amount` as `--amt`, the missing-flag repair then added `--amount`, and the
adapter consumed only the canonical flag.  Closing the option names made the
abbreviation unrepresentable.

Measured on expenses with the shared prefix and Qwen3-4B Q4_K_M:

| Extraction | Wall | Generated | Blockers |
| --- | ---: | ---: | ---: |
| Split, before option closure | 249.3 s | 9,022 | 6 (three unconsumed flags) |
| Split, after option closure | 250.5 s | 9,018 | **2 (review only)** |

The split path is not faster for Qwen: the plan call plus two group calls cost
about the same as the single components call.  It is useful because it bounds
each call's output and makes the explicit command surface predictable.

#### Split is not used when the prompt states no command lines (measured 2026-11-12)

The split path exists to divide explicitly named command groups.  On a
prose-only prompt it first has to invent the groups, and each group call then
has no required line to fill.  `ESUS_COMPONENTS_SPLIT=1` is now ignored when
`extract_command_lines` returns nothing; the log says
`[ok] step components: split disabled — no command lines to divide into groups`
and the single components call runs.

Measured on `prompts/prompt_60.txt`, Qwen3-4B Q4_K_M, 16k context, one slot,
same code and flags (the only difference is the auto-disable):

| Extraction | Wall | Generated tokens | Steps | Components calls |
| --- | ---: | ---: | ---: | ---: |
| Split: plan + 13 group calls | 651.0 s | 24,499 | 23 | 14 |
| No command lines: split disabled | **278.9 s** | **10,438** | **8** | **1** |

The adapter step stayed one call in the faster run: 3,414 tokens in 94.8 s.
Both runs were unreviewed and report the same single open-review blocker
(8 contracts in the split run, 7 in the faster one); the faster surface has
three more residual risks (15 against 12).

The surface itself differs.  The single call chose a `SearchService`, made
`Product search`/`Product export` leaves, and omitted `OrderItem` from
`crud_services`.  With the preserved 60 grounding review applied (it drops the
unrequested `ExportService`), a mechanical `OrderItemRepository` shell and its
`get_order_items_by_order_id` query, the generated program passes 10/10.  Without
that completeness repair the faster extraction loses the item repository and
the same acceptance suite stops at 2/10.  The 57% extraction saving is real,
but a prose-only prompt with a domain needs the completeness pass before the
split can be dropped uncritically.

### Mechanical interaction adapters (default, measured 2026-11-12)

`ESUS_MECHANICAL_ADAPTERS=1` is the default in the extraction pipeline and the
validation runner (set it to `0` to force the model).  The pass derives step G
from the command surface, the service signatures and the data model instead of
asking the model to copy them.  A leaf whose target method is ambiguous, or
whose flags do not all resolve to parameters, declines the whole derivation and
falls back to the model, so the semantic choices stay with the LLM.

| Prompt | Adapters | Model call saved | Tokens saved | Readiness |
| --- | ---: | ---: | ---: | --- |
| Library (explicit surface) | 10 | 34.2 s | 1,174 | unchanged (0 blockers) |
| Expenses (explicit surface) | 14 | 64.7 s | 2,359 | unchanged (0 blockers) |
| Inventory (explicit surface) | 11 | 41.7 s | 1,553 | unchanged (0 blockers) |
| GUI (no CLI surface) | 0 | **96.1 s** | **3,424** | unchanged (11/11 acceptance) |
| `60` (prose surface, split off) | 18 | 94.8 s | 3,414 | unchanged (1 open-review blocker) |

A non-CLI facade has no command-line input to adapt: the GUI emitter binds its
CRUD panels straight to the repositories/services.  The adapter step now writes
an empty list instead of asking the model, and the GUI acceptance suite still
passes 11/11.

The explicit-surface runs pick the same targets as the model, with two benign
differences: the public service wrapper wins over its repository, and a
primary-key lookup is `DIRECT` rather than `LOOKUP_ID` (both pass the integer
unchanged).  On `60` the model still chooses the surface and the actions; the
mechanical pass fills their targets, flags, transforms and required flags.
With split off and mechanical adapters, extraction falls from 651.0 s / 24,499
tokens to **175.3 s / 7,149 tokens** (7 steps, no adapter model call).  The
dependent-entity completion also adds `OrderItemRepository` and its
`get_order_items_by_order_id` query; with the preserved review answers the
generated program passes **10/10** of the 60 acceptance checks.

The initial prompts were rechecked on the same code and review inputs:
hello **1/1**, CLI tool **1/1**, GUI **11/11**, inventory **8/8**, expenses
**15/16 then 16/16 after one repair pass**, library **18/18**.  A prose GUI
keeps the plan surface: the single prose call can drop a CRUD operation, so
when its facade is `gui`/`api` the step asks for the plan it used before and
keeps that answer.  The generated library, inventory and expenses programs
also pass their acceptance suites (**18/18, 8/8, 16/16**) with mechanical
adapters.

### Domain triage (default in `main.py`, measured 2026-11-12)

`main.py` sets `ESUS_DOMAIN_TRIAGE=1` by default.  It asks one single-letter
question before extraction: does the program define named domain entities with
fields?  `Y`/`U` runs the normal pipeline; `N` skips extraction and lets the
generator write the one-file `app.py` from the requirements.  The triage prompt
was tested on the six initial prompts and all sixty validation prompts: **66
answers, 62 Y, 4 N, 0 U, 0 false N**; the four `N` prompts were hello,
cli_tool and two equivalent validation prompts.  The call took **15.2 s total
for 66 prompts** (mean 0.23 s, max 0.86 s), so its cost is negligible beside
the steps it can skip.

With triage and the mechanical service wrappers, the six initial prompts
total **691 s / 21,643 tokens** against the baseline
**1,333 s / 35,430 tokens** (-48% / -39%).  Per prompt:

| Prompt | Baseline | Now |
| --- | ---: | ---: |
| hello | 14 s / 375 tokens | **4 s / 156 tokens** |
| cli_tool | 39 s / 1,474 tokens | **14 s / 519 tokens** |
| gui | 272 s / 7,692 tokens | **118 s / 3,758 tokens** |
| inventory | 238 s / 6,587 tokens | **118 s / 3,828 tokens** |
| expenses | 471 s / 11,324 tokens | **268 s / 7,348 tokens** |
| library | 299 s / 7,978 tokens | **169 s / 6,034 tokens** |

GUI improves because a non-CLI facade no longer asks the model for CLI input
adapters: the GUI emitter binds its CRUD panels directly, and the GUI
acceptance suite passes with an empty adapter list.  The plan-surface guard
still costs one components call, but the skipped adapter call is much larger.
Library's generation was remeasured at 46 s in this pass (24–46 s across runs);
its code path did not change.




### Mechanical service CRUD wrappers (measured 2026-11-12)

A service method named exactly after one entity's CRUD verb (`create_customer`,
`update_order`, `delete_product`) and whose parameters map one-for-one to that
repository method is now emitted mechanically.  The wrapper is refused when the
description names another rule (budget, capacity, validation), when a reviewed
repair exists, or when the contract carries effects/reads/derives.

On `prompt_60` the last four stubs are now mechanical too: a two-hop
repository filter (`Customer -> Order -> Invoice`), a lookup through a named
relation (`Product by Category.name + Product.name`), a status-count report and
a product-stock report.  The emitted program is **100% mechanical**:

| | Before | After |
| --- | ---: | ---: |
| LLM bodies | 14 | **0** |
| Generation wall | 179 s | **~1 s** |
| Generation output tokens | 1,303 | **0** |
| **Total `60`** | 791.9 s / 25,593 tok. | **176.3 s / 7,149 tok.** |
| Acceptance | 10/10 | **10/10** |

Inventory also gained mechanical low-stock and stock-value queries, plus the
mapping update; its generation is now fully mechanical:

| | Before | After |
| --- | ---: | ---: |
| LLM bodies | 8 | **0** |
| Generation wall | 60 s | **~1 s** |
| Generation output tokens | 900 | **0** |
| **Total inventory** | 238 s / 6,587 tok. | **118 s / 3,828 tok.** |
| Acceptance | 8/8 | **8/8** |

Expenses gained mechanical period aggregates, the CSV export and recurring
detection.  The monthly/yearly report bodies and the budget status remain
LLM-written because their output keys/status words come from the wording of
the requirement, not from the data model; writing those keys mechanically
would be prompt overfitting.

| | Before | After |
| --- | ---: | ---: |
| LLM bodies | 10 | **5** |
| Generation wall | 207 s | **88 s** |
| Generation output tokens | 3,237 | **1,618** |
| **Total expenses** | 471 s / 11,324 tok. | **268 s / 7,348 tok.** |
| Acceptance | 16/16 | **16/16** |

The CSV export no longer ends in a stub, so the second generation/repair pass
is **eliminated**: the acceptance suite is 16/16 on the first pass, with **0
repair asks**.

Library gained a mechanical text search (title, ISBN, related author name), a
mechanical overdue read and a search delegation; only `renew_membership`
remains LLM-written:

| | Before | After |
| --- | ---: | ---: |
| LLM bodies | 4 | **1** |
| Generation wall | 46 s | **2 s** |
| Generation output tokens | 413 | **52** |
| **Total library** | 299 s / 7,978 tok. | **169 s / 6,034 tok.** |
| Acceptance | 18/18 | **18/18** |

GUI gained mechanical count-by-type, contained-name filtering and a list-filter
delegation; five business guards/summaries remain LLM-written:

| | Before | After |
| --- | ---: | ---: |
| LLM bodies | 8 | **2** |
| Generation wall | 82 s | **12 s** |
| Generation output tokens | 988 | **320** |
| **Total GUI** | 272 s / 7,692 tok. | **118 s / 3,758 tok.** |
| Acceptance | 11/11 | **11/11** |

Across the six initial prompts, the cumulative state is now
**691 s / 21,643 tokens** against the baseline **1,333 s / 35,430 tokens**
(-48% / -39%).  Adding `prompt_60` gives **867 s / 28,792 tokens** against
the 2026-11-10 GPT-6 Luna run's **1,145 s**, a ratio of **0.76×** — ESUS was
24% faster in that aggregate, with the same acceptance coverage.



### GPT-6 Luna rerun (measured 2026-11-13)

The end-to-end comparison was repeated with the same protocol: one subagent per
prompt, the prompt file as the only specification, GPT-6 Luna through OpenCode
Go (`opencode-go/gpt-6-luna`), Python 3.12.  The seven original agents started
together; the times below are individual wall-clock measurements, not a
sequential total.  The first expenses agent hit a stuck tool call after writing
its files.  The benchmark keeps that run at its full **375.4 s** wall time,
because the stalled stream is part of the latency a user would experience; a
clean **126.9 s** rerun confirms the prompt can complete without the stall but
is not used for the timing.

| Prompt | ESUS | GPT-6 rerun | ESUS / direct | Direct own tests |
| --- | ---: | ---: | ---: | --- |
| Hello world | 4 s | 11.5 s | 0.35× | 2/2 |
| CSV → JSON CLI | 14 s | 37.3 s | 0.38× | 10/10 |
| Inventory | 118 s | 104.1 s | 1.13× | 5/5 |
| Wine GUI | 118 s | 132.6 s | 0.89× | 8/8 service |
| Expenses | 268 s | 375.4 s | 0.71× | 5/5 |
| Library | 169 s | 154.2 s | 1.10× | 9/9 |
| Small business (`60`) | 176.3 s | 104.7 s | 1.68× | 8/8 |
| **Six initial prompts** | **691 s** | **815.1 s** | **0.85×** | |
| **All seven** | **867 s** | **919.8 s** | **0.94×** | |

A ratio above 1 means ESUS was slower.  With the stalled expenses stream
included, the direct total is **19.7% faster than the 2026-11-10 direct run**
(919.8 s versus 1,145 s), but ESUS is slightly faster in this aggregate
(867 s versus 919.8 s); the six initial prompts are 0.85×.  The seven direct
agents overlapped, so the actual batch wall was about 375 s, dominated by the
stalled expenses run; the sums are the sequential-equivalent used for the
comparison with ESUS.

Direct token use was **1,448,826 input buckets** (1,347,731 of them cache
reads), **65,445 output tokens**, **14,692 reasoning tokens** and **$0.0662**
reported API cost.  ESUS used **28,792 tokens** for the same seven prompts.
The accounting is not directly comparable: the direct figure includes repeated
cached context, tool calls and test writing, while ESUS counts extraction and
generation prompts/outputs only.

All seven direct projects import and pass their own tests on **Python 3.12**
(47 tests total; the previous direct expenses and library outputs failed to
import on 3.12).  The independent `tests/chatgpt_acceptance/` harness is
layout-bound: hello passes **4/4** after the entry file is copied to `app.py`,
and the CLI suite passes **10/10** after a small positional-output shim
(**8/10** as delivered, with only the output-file syntax differing).  The other
outputs chose different package and service layouts from the preserved direct
fixtures, so the old 91-check total cannot be reused without adapters.  A
rerun-specific harness was added at `tests/gpt6_rerun_acceptance/`: it reports
**73/73 checks** on Python 3.12 — hello 4, CLI 10, inventory 13, GUI 9,
expenses 11, library 12 and `60` 14.  The GUI checks cover the domain rules,
persistence and tkinter wiring, not a live frame: this Python lacks `_tkinter`.
The new harness is not the old 91-check suite; it drives the rerun's public
APIs and CLI.  The two runs are materially different implementations: the old
inventory used repository subpackages while the rerun uses a flat module; the
old `60` used `src/shop/database.py` while the rerun uses `shop/db.py`; the old
GUI was a PyImgui/GLFW `wine_inventory` package while the rerun is a flat
tkinter application.  Same prompts and model, different layouts and service
contracts.  ESUS still has the stronger acceptance evidence: **65/65**
external checks, including a real GUI launch.

The direct code is much smaller: roughly 700–850 source lines per substantive
app, versus 1.6k–2.2k in the preserved ESUS outputs.  It is also less
reproducible across runs: the same prompts produced different layouts and CLI
option shapes from the 2026-11-10 direct run.

### What the rerun does and does not establish (2026-11-13)

The result supports a narrower conclusion than "one system writes better code".
This table separates what was measured from what is still a hypothesis.

| Claim | Verdict | Evidence and caveat |
| --- | --- | --- |
| ESUS is about as fast, sometimes faster | **Sequential-equivalent only** | 867 s versus 919.8 s for the sum of individual direct runs; 691 s versus 815.1 s on the six initial prompts. The seven direct agents ran concurrently, so their batch wall was about 375 s; ESUS uses one llama slot sequentially. Per prompt, direct was faster on inventory, library and `60`; ESUS was faster on hello, CLI, GUI and expenses. Latency conclusions therefore depend on the scheduling model. |
| ESUS is deterministic | **Cold first pass, in practice** | `kernel/extraction/pipeline.py` uses `TEMPERATURE = 0.0` and `SEED = 20261012`; `generator.py` uses the same policy for fallback. But retries use `RETRY_TEMPERATURE = 0.35`, GPU arithmetic can vary, and a model, quantization, server or review-fixture change changes the output. "Same prompt, same code" is not a bit-for-bit guarantee. |
| ESUS uses far fewer tokens | **Yes, with a measurement caveat** | ESUS used 28,792 tokens for the seven prompts. Direct used 1,448,826 input buckets (including 1,347,731 cache reads), 65,445 output tokens and 14,692 reasoning tokens. The two accountings are not identical because the direct figure includes repeated cached context, tool calls and test writing, but the order of magnitude is clear. |
| ESUS output is functional and conformant by default | **On the tested reference prompts** | **65/65** external checks on the six initial prompts plus `60`, with **0 repair asks** in the latest run. The acceptance tests are prompt-specific; validation prompts 01–59 are outside that suite. This is strong evidence for the reference corpus, not a guarantee for every future prompt. |
| GPT-6 Luna is sometimes faster | **Yes** | It was faster on inventory, library and `60` in individual wall time, and its parallel batch finished in about 375 s. Its sequential-equivalent sum is slower because one expenses stream stalled for 253 s; that stall is included in the user-facing latency. |
| GPT-6 Luna uses much more context | **Yes** | The 1.45M input buckets and 65k output tokens above are far above ESUS's 28.8k total, even after allowing for the different accounting. The reported API cost was $0.0662 for the seven prompts. |
| The GPT-6 API is unstable | **One observed stall, not a reliability rate** | One response stream stayed in `streaming` with empty tool arguments for about 253 s, then completed. The other six streams ran normally. The evidence does not isolate provider server, network/SSE or client handler, so this is a real risk to monitor, not a measured failure rate. |
| GPT-6 is nondeterministic | **Observed** | The same prompt produced different package layouts, service APIs and CLI shapes from the 2026-11-10 run. This may come from sampling, tool choices or model/version changes; for greenfield code it is tolerable, for brownfield review and reproducibility it matters. |
| ESUS will scale better on larger projects | **Plausible for greenfield, unproven** | Mechanical CRUD and deterministic emitters reduce repeated model work, but the extractor uses a small Qwen model and a 16k context; larger specifications mean more documents, more review and potentially more blockers. There is no larger greenfield benchmark, and ESUS is not a repository-navigation agent. For brownfield work, an agent with file access is currently the better fit. |
| ESUS is better for sovereignty and sensitive data | **Conditional advantage** | A local `llama-server` keeps prompts and code on the machine if there is no telemetry. Model provenance/license (Qwen), host security, local logs and generated dependencies still matter. GPT-6 sends code and context to an external provider, so retention/region/DPA must be checked. Neither system should receive credentials in prompts; a direct agent with repository access also needs a sandbox and secret redaction. |

**Recommended conclusion.** Use ESUS for repeatable greenfield generation where
external acceptance, low token cost and local data matter. Use GPT-6 Luna for
fast one-shot exploration or brownfield work where an agent can inspect a
repository, but sandbox it, redact secrets, record the model/version and treat
the output as reviewable rather than reproducible. Do not claim that ESUS
scales better until it has a larger greenfield benchmark and a brownfield
prototype; do not claim that the GPT-6 API is reliably fast until more runs
quantify the stream-stall rate. For latency, always state both the
sequential-equivalent sum and the parallel batch wall, because they lead to
opposite conclusions.

### Fresh post-merge generation (2026-11-13)

A fresh generation from the merged `main` with the preserved review sidecars
(`ca7e255^:backup/review-inputs-2026-11-10`) generated all seven prompts and
passed all seven acceptance suites. Its final wall times were **947.3 s** total:
hello 5.7 s, CLI 13.6 s, GUI 122.1 s, inventory 123.4 s, expenses 288.7 s,
library 200.8 s and `60` 192.9 s.

This does not reproduce the **867 s** figure exactly. The fresh extraction
produced different documents for some prompts: library generated a dead
`overdue --overdue` flag and asked for three provisional bodies instead of one,
while the `60` command surface also differed. A library surface review decision
and one rerun were needed. This is extraction/run-state variation, not a
`generator.py` merge regression. The 867 s figure remains a measured run, not a
bit-for-bit guarantee.

### Mechanical extraction passes (measured 2026-11-06)

The deterministic passes above were measured together on expenses, Qwen3-4B
Q4_K_M, split components, 1 slot, 16k context:

| Extraction | Wall | Generated tokens | Blockers |
| --- | ---: | ---: | ---: |
| Deterministic CRUD classification + adapter rename | 239.5 s | 9,152 | 2 |
| Plus mechanical schema invariants | **232.5 s** | **8,965** | 2 |
| Plus mechanical service CRUD only (`ESUS_MECHANICAL_SERVICES=1`) | 211.5 s | 8,274 | 2 |
| Plus both mechanical schema and service CRUD | **200.9 s** | **8,087** | 2 |

The schema pass changed only the invariant step (611 -> 424 tokens, 15.3 ->
12.6 s); the rest of the wall difference is run-to-run variation. The adapter
rename removed a 258-token retry and the `expensecategoryupdate` unknown-field
blocker. `ESUS_MECHANICAL_SCHEMA=1` remains opt-in until a reviewed run passes
acceptance; the classification and adapter repairs are on by default because
they do not change a prompt.

The service-CRUD pass reduced the contract call from 2,251 to 1,078 tokens
(about 59 s to 27 s) and total extraction from 9,152 to 8,274 tokens. It only
completes services the model already named: inventing `CategoryService` and
`BudgetService` made the adapter mapping worse, so a missing service is left to
the repository contract. `ESUS_MECHANICAL_SERVICES=1` is therefore opt-in, and
the combined schema + service run has 0 open ties after the deterministic `read_all`-with-parameters fix.

A mechanical not-found error pass was tried and removed: the shorter error
registry changed the service-contract call enough to truncate and retry it
(3,584 + 3,757 tokens), taking the run from 2 to 7 blockers. That is not a safe
trade for the roughly 100 tokens it saved.

### Parallel extraction (opt-in, measured slower)

`ESUS_PARALLEL=1` overlaps the independent extraction branches: errors and
invariants after step B, the two split command groups, and pattern matching and
adapters at the end. It is extraction-only; the generator still loads its
backend with a pinned slot so body caching is unchanged. The server must have
more than one slot and enough context for both:

```bash
CTX=32768 SLOTS=2 ./scripts/start_llama_server.sh
ESUS_COMPONENTS_SPLIT=1 ESUS_PARALLEL=1 python3.12 extract_arch.py \
    --model server --output out/expenses_parallel \
    --requirements prompts/initial/prompt_expenses.txt --no-chat --quiet
```

Measured on the expenses prompt, Qwen3-4B Q4_K_M, split components, 16,384
tokens per slot, temperature 0:

| Extraction | Wall | Generated tokens | Blockers |
| --- | ---: | ---: | ---: |
| Sequential (1 slot, 16k ctx) | **278.6 s** | 9,792 | 4 |
| Sequential (2 slots, 16k/ctx) | 279.0 s | 9,792 | 4 |
| Parallel (2 slots, 16k/ctx) | 301.8 s | 9,792 | 4 |
| Sequential (2 slots, 32k/ctx, `--cache-ram 4096 --kv-unified`) | 298.3 s | 9,792 | 4 |
| Parallel (2 slots, 32k/ctx, `--cache-ram 4096 --kv-unified`) | 343.2 s | 9,792 | 4 |

The extraction documents had the same decisions and the same 4 blockers. The
only document difference was the classifier's confidence values in
`pattern_matches.json`; the pattern choices were unchanged. Per-request decode
fell to about 17–35 tok/s while two requests shared the GPU, against 34–42 tok/s
sequential, and the adapter step grew from 55.8 s to 68–78 s when it overlapped
pattern classification. The split command groups also took longer together
(68–76 s) than one after the other (49 s).

Additional experiments with `--cache-ram 4096` and `--kv-unified` made both
sequential and parallel slower (298 s vs 279 s sequential; 343 s vs 302 s
parallel), likely because unified KV cache adds coordination overhead and the
memory-bandwidth limit is already saturated.

This machine is memory-bandwidth-bound, so adding concurrent sequences buys no
wall-clock time. The option is therefore **off by default** and should not be
used for production runs. A machine with more memory bandwidth, or a workload
whose critical path is mostly prompt prefill, could behave differently; measure
before relying on it.


### Same extraction conditions, two prompts (measured 2026-11-09)

Both prompts were extracted with the same opt-in flags:

```bash
ESUS_COMPONENTS_SPLIT=1 ESUS_MECHANICAL_SCHEMA=1 ESUS_MECHANICAL_SERVICES=1 \
  python3.12 extract_arch.py --model server --no-chat --output OUT \
    --requirements PROMPT
```

| Prompt | Extraction | Generated tokens | Review blockers | Generation |
| --- | ---: | ---: | ---: | --- |
| Expenses | 217.9 s | 8,087 | 0 | 24 mechanical / 9 LLM bodies; 13/13 acceptance |
| Library | 188.6 s | 7,154 | 0 | 28 mechanical / 6 LLM bodies; 17/17 acceptance |

The library run started at 4 blockers and exposed three split-path defects
rather than model-facing prompt problems: the merged command groups repeated a
subcommand and an option, a flat `library overdue` line came back as `overdue
library --overdue`, and a split group wrote `--copies` as required although
the requirements prose says it defaults to one. The repairs are deterministic
(deduplicate the merged surface, fold a program-word subcommand, and read an
optional/default flag from the requirements or model) and the expenses surface
is unchanged by them. On the generation side, repository list returns are now
normalized to model objects and deduplicated by id, and bare error classes are
qualified as `errors.Name`; this removed the library's unhashable-dict search
failure and two refused service bodies. Library generation reached 28
mechanical bodies and 6 provisional LLM bodies, down from 24 and 8 under the
previous conditions.

### Other prompts, same conditions (measured 2026-11-09)

The same three flags were used for the remaining prompts. Each now has a
behavior acceptance test: `tests/e2e_<name>_acceptance.py`. Timing is one run
on the local Qwen3-4B server, 16k context, not a best-of-N.

| Prompt | Extraction | Generation | Generated surface | Acceptance |
| --- | ---: | ---: | --- | --- |
| `hello_world` | 7.7 s | 1.5 s | direct `app.py` fallback | 1/1 |
| `cli_tool` | 25.0 s | 13.9 s | direct `app.py` fallback | 1/1 |
| `inventory` | 155.9 s | 62.9 s | 2 entities, 2 repositories, 1 service; 13 mechanical / 9 LLM bodies | 7/7 |
| `gui` | 183.8 s | 127.3 s | 2 entities, 2 repositories, `gui.py` panels for Wine and StorageLocation; 16 mechanical / 12 LLM bodies | 8/8 |
| `60` | 509.2 s | 224.2 s | 6 entities, 6 repositories, 13 services; 41 mechanical / 21 LLM bodies | 9/9 |

The fallback prompts have no domain documents (no models, services or
adapters); the command table alone is not architecture, so the generator now
writes `generated/app.py` from the requirements instead of an UNBOUND shell.
The GUI's extractor selected `tkinter`, for which no emitter exists; the
declaration is normalized to the supported `pyimgui` backend, while the
panels and CRUD wiring still come from the documents. The inventory prompt
exposed three-word flagless paths (`product report low-stock`); they are now
included when their command word is already known. The 60 prompt needed assistant-filled review contracts and the split surface
repairs (subcommand deduplication, program-word folding and adapter-backed
grouping) before it reached an acceptance run.  A clean rerun
with no document patching — only the assistant-filled review records — reached
0 blockers, generated from the final code, and passed 9/9; that run took
509.2 s to extract and 224.2 s to generate, with 41 mechanical and 21
provisional bodies.  The three lifecycle methods are emitted from reviewed
declarative programs (`method_programs.json`), not from an order-specific
emitter; the interpreter supports generic read/query/check/for-each/update/
create/assign actions.
