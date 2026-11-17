# Where ESUS spends its time, and how to make it faster

This page records measurements and the ideas they suggest. Some ideas are implemented and measured; each section says which. Figures marked *measured* come from the server's own timings or a wall-clock run; figures marked *estimate* are guesses to be checked before anyone relies on them.

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
5. **Run generation requests in parallel (`-np 2` to `4`).** Not implemented. Decoding on this GPU is limited by memory bandwidth, so serving several sequences at once may raise aggregate throughput, but body prompts also share a long prefix that a single slot reuses across requests. Each parallel slot needs its own context and cache, and the body prompts would have to be built from the same base text so the result does not depend on which request finishes first.
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
