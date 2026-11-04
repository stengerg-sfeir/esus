# Where ESUS spends its time, and how to make it faster

This page records a measurement of one complete run and the ideas it suggests. Nothing here has been implemented. Figures marked *measured* come from the server's own timings; figures marked *estimate* are guesses to be checked before anyone relies on them.

## What was measured

One clean run of the library prompt (`prompts/prompt_library_system.txt`), on an Apple M1 Pro with 16 GB, Qwen3-4B-Instruct Q4_K_M through `llama-server` with one slot, 16,384 context, the Metal GPU and flash attention. The numbers come from the `print_timing` lines of the server log.

| Phase | Wall time | Measured detail |
| --- | --- | --- |
| Extraction | about 10 min | 172 requests. **Decoding 539 s for 21,013 tokens (about 39 tok/s), 88% of the phase.** Prompt processing 70 s for 26,283 tokens. |
| Generation | about 7.5 min | 26 requests. **Prompt processing 381 s for 131,180 tokens (about 5,000 tokens per request, about 344 tok/s), 86% of the phase.** Decoding 63 s for 2,127 tokens. |

Other measured facts:

- Extraction is a chain: each step needs the documents of the earlier ones, so its model calls cannot run side by side. Thirteen generation calls produce the documents (`service_contracts` and `persistence_ports` are the largest, 2,400 to 3,100 tokens each, about 70 to 88 s each). About 84 further calls classify methods into patterns.
- The review loop reran five of those calls (components to persistence) in a second round, about 230 s, 39% of the extraction. A run without the review loop (`main.py` by default) took 6m 13s on the expenses prompt.
- Only 2 of the 24 model-written bodies needed a repair ask, so repairs are not where the generation time goes.
- Runs are deterministic: the same code, model, server flags and context give byte-identical documents, model answers and generated modules (three runs, two after cold server restarts). That makes caching by prompt safe, and it means any change that alters a prompt changes the output once.

## The two phases need different fixes

**Extraction is decode-bound.** The model writes about 21,000 tokens at a fixed rate, and everything else is small. Only generating fewer tokens, or generating them faster, helps.

**Generation is prompt-bound.** Each body prompt re-sends about 5,000 tokens (the rules, the requirements, the module text and the API reference), and decoding the body itself is cheap. Reusing work across requests helps far more here than a faster decoder.

## Ideas, in the order I would try them

1. **Put the shared part of the body prompt first.** The method's own name appears near the top of the rules, so successive prompts share almost no prefix and the server cannot reuse its cache. With the method-specific part last, the long shared part is processed once and reused. *Estimate:* prompt processing falls by about 4 times, generation to 2 to 3 minutes. First measure how much of the prefix is actually reused (the server log reports it). The module text also changes as bodies are written into it; bodies are written from the bottom of the file upwards, which should keep the top stable, but that is unchecked. This changes every body prompt, so the output changes once, and acceptance must be rerun.
2. **Cache every model call by its prompt.** Key a stored answer by the model, the server settings, the prompt text and the sampling parameters. An unchanged rerun then takes seconds, and a rerun after a change recomputes only the calls whose prompt changed. It is safe because the same input gives the same output. It does nothing for a first run, but it is what removes the 8 to 15 minute wait from every fix-and-retry loop.
3. **Speculative decoding for extraction.** `llama-server -md` takes a small draft model; output that follows a JSON grammar is very predictable. *Estimate:* 1.5 to 2 times faster decoding. It needs a small model of the same family (the 0.6B model in the models folder is a reranker and does not qualify), about 0.5 GB more memory, and a test that it works with the grammar sampler. Output may differ slightly from today's because of numerics.
4. **Run generation requests in parallel (`-np 2` to `4`).** Decoding on this GPU is limited by memory bandwidth, so serving several sequences at once raises the total rate. It suits generation only, since extraction steps depend on each other. Each slot needs its own context (three slots of 8,000 tokens is about 3.5 GB of cache at full precision), and the body prompts would have to be built from the same base text so that the result does not depend on which request finishes first.
5. **Smaller prompt blocks.** Showing only the target class's methods instead of the whole module cuts prompt processing, but the `exact` context was tuned for the small model, so this risks the quality of the bodies.

## What I would not do

- **A smaller model.** Decoding would be faster, but more bodies would be refused by the gates, and every repair ask costs a full prompt. A weaker model on structured JSON also risks the documents themselves.
- **Shorter descriptions in the documents.** The descriptions are about 30% of the characters of the two largest documents (measured on the final JSON: 29% of `service_contracts`, 32% of `persistence_ports`), so shortening them would save a real share of the decoding, but the contract review reads them: "Sets return_date to today, status to 'returned', and increments available copies" is where a contract's effects come from. Shortening them would lose requirements.
- **Looser sampling or fewer tokens in the budget.** It would trade correctness for seconds.

## Open questions for any speed change

- Does it change the output? Any change to a prompt, a catalogue, a check's message or the numerics changes the generated code once. Rerun the acceptance test, and keep `out/library_correct` as the reference for comparison.
- Does it hold on other machines? Timings and floating-point behaviour depend on the hardware and the llama.cpp build.
