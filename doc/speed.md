# Where ESUS spends its time, and how to make it faster

This page records a measurement of one complete run and the ideas it suggests. The prompt reordering and the server launch script are implemented; the remaining ideas are not. Figures marked *measured* come from the server's own timings; figures marked *estimate* are guesses to be checked before anyone relies on them.

## What was measured

One clean run of the library prompt (`prompts/prompt_library_system.txt`), on an Apple M1 Pro with 16 GB, Qwen3-4B-Instruct Q4_K_M through `llama-server` with one slot, 16,384 context, the Metal GPU and flash attention. The numbers come from the `print_timing` lines of the server log.

| Phase | Wall time | Measured detail |
| --- | --- | --- |
| Extraction | about 10 min | 172 requests. **Decoding 539 s for 21,013 tokens (about 39 tok/s), 88% of the phase.** Prompt processing 70 s for 26,283 tokens. |
| Generation | about 7.5 min | 26 requests. **Prompt processing 381 s for 131,180 tokens (about 5,000 tokens per request, about 344 tok/s), 86% of the phase.** Decoding 63 s for 2,127 tokens. |

Other measured facts:

- Extraction is a chain: each step needs the documents of the earlier ones, so its model calls cannot run side by side. Thirteen generation calls produce the documents (`service_contracts` and `persistence_ports` are the largest, 2,400 to 3,100 tokens each, about 70 to 88 s each). About 84 further calls classify methods into patterns.
- The review loop reran five of those calls (components to persistence) in a second round, about 230 s, 39% of the extraction. A run without the review loop (`main.py` by default) took 6m 13s on the expenses prompt.
- Repair asks were rare in the older reference run (2 of the 24 model-written bodies), but the current timing run saw 5 and 75.7 s of first attempts; see [Per-answer timing record](#per-answer-timing-record).
- Runs are deterministic: the same code, model, server flags and context give byte-identical documents, model answers and generated modules (three runs, two after cold server restarts). That makes caching by prompt safe, and it means any change that alters a prompt changes the output once.

## Per-answer timing record

`<out>/llm_stub_answers.json` now records, beside every body answer, `seconds` (wall), `decode_seconds`, `prompt_tokens` and `cached_tokens`; a repaired body also has `first_*` for its first attempt. The `prompt_tokens` figure is the total context offered, so `prompt_tokens - cached_tokens` is the new prefill the server actually processed.

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
4. **Run generation requests in parallel (`-np 2` to `4`).** Decoding on this GPU is limited by memory bandwidth, so serving several sequences at once raises the total rate. It suits generation only, since extraction steps depend on each other. Each slot needs its own context (three slots of 8,000 tokens is about 3.5 GB of cache at full precision), and the body prompts would have to be built from the same base text so that the result does not depend on which request finishes first.
5. **Smaller prompt blocks.** Showing only the target class's methods instead of the whole module cuts prompt processing, but the `exact` context was tuned for the small model, so this risks the quality of the bodies.

## Server launch

Use `scripts/start_llama_server.sh`. Its defaults are the measured model, one slot, 16,384 context, six threads, flash attention, 1024-token batch/ubatch and context shifting. It does **not** set `--cache-ram`; llama-server's own default is left untouched. Speculative decoding is opt-in because it measured slower on this machine:

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

## MLX backend (measured 2026-11-05)

The MLX backend is selected with `--model mlx` and runs in a Python 3.12
virtualenv (`.venv-mlx`); MLX has no wheel for the system Python 3.14. The model
is the 4-bit MLX conversion
`mlx-community/Qwen3-4B-Instruct-2507-4bit`, not the Q4_K_M GGUF used by
llama.cpp. GBNF is translated to Lark and enforced by llguidance's MLX bitmask
kernel; see [doc/mlx.md](mlx.md).

Measurement conditions: quiet M1 Pro 16 GB, no llama-server running, one MLX
process, same prompt and temperature 0.

| Phase | llama.cpp 0.9.0 | MLX 4-bit |
| --- | ---: | ---: |
| Expenses extraction, wall | 397.4 s | **372.1 s** |
| Extraction model time | 385.1 s | **296.9 s** |
| Extraction generated tokens | 13,837 | 12,597 |
| Expenses generation, wall | **107.9 s warm** | 135.0 s |
| Expenses generation, decode | ~50 s | 50.0 s |
| Generation prompt tokens | 51.9k / 38.7k cached | 54.0k / **29.2k cached** |
| Expenses acceptance | **13/13** | **11/13** |

Extraction is about **6% faster wall-clock** and about **23% faster in model
time**. The remaining extraction time is the classifier, which does one full
forward pass per candidate set on MLX; the llama.cpp server reuses its KV prefix
there. Raw extraction uses the MLX KV cache only in the opt-in shared-context
mode described below; the original prompt layout has no useful common prefix.

Body generation is **slower** than a warm llama-server: MLX prefill is slower
and the 4-bit MLX weights do not reproduce the llama.cpp Q4_K_M output. The
common expenses acceptance score is **11/13** (the recurring-expense check and
one service check fail), so MLX should currently be treated as a speed experiment
rather than a replacement for the llama.cpp path. Its generation run with KV
cache disabled took 223.4 s; the 135.0 s figure is with the shared body-prompt
prefix cached.

### Shared extraction prefix (opt-in)

`ESUS_SHARED_CONTEXT=1` moves the requirements into a fixed first system turn
and puts the step-specific instruction in the user turn. Every extraction prompt
then begins with the same **3,225-character** requirements prefix, so both
backends can reuse it:

```bash
ESUS_SHARED_CONTEXT=1 .venv-mlx/bin/python main.py prompts/prompt_expenses.txt \
    --model mlx -o out/expenses_mlx_shared
ESUS_SHARED_CONTEXT=1 python3 main.py prompts/prompt_expenses.txt \
    --model server -o out/expenses_llama_shared
```

Measured on the expenses prompt, same model and temperature:

| Extraction | Baseline | Shared prefix | Change |
| --- | ---: | ---: | ---: |
| MLX wall | 372.1 s | **307.5 s** | **-17%** |
| MLX model time | 296.9 s | **229.6 s** | **-23%** |
| MLX generated tokens | 12,597 | 10,315 | fewer retries |
| llama.cpp wall | 397.4 s | **326.8 s** | **-18%** |
| llama.cpp generated tokens | 13,837 | 11,913 | fewer retries |

The speed gain is real, but the prompt change also changes the documents:
the MLX shared run had 20 readiness blockers (baseline 24) and the llama.cpp
shared run had 18 (baseline 4). It is therefore **off by default** until a
reviewed shared-context run passes the same end-to-end acceptance suite. The
flag is the experiment; do not treat it as a free cache on the current prompts.

Blocker counts count report lines, not independent defects, and every run above
is **unreviewed**. The llama.cpp baseline's 4 were three open review questions
plus one wrong adapter field; the shared run's 18 were three review questions,
six wrong adapter fields, and nine CLI options left unconsumed. The 18 is a
worse extraction, not a slower or broken llama.cpp engine, and neither count is
an acceptance score: the reviewed `out/expenses_correct` is the 13/13 reference.
The MLX baseline's 24 and shared run's 20 have the same character — a few root
causes repeated per field or option — and the MLX outputs are also from a
different 4-bit quantisation than the Q4_K_M GGUF.

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
