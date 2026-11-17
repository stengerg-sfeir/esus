# ESUS open points

Open work that is known, measured where possible, and not yet done. Each entry says what is open, the evidence, and the next step. A completed item is removed from this file; its history stays in the archived plan,
`doc/archive/fix-plan-library-generation.md`.

## 1. Readiness notes should explain themselves

**Open.** A readiness note such as `narrow_margin`, `low_confidence`, `corrected_claim` or `missing_pattern` reads like a warning, but it only describes how a method was generated: how sure the classifier was, whether two labels were close, whether the catalogue has no pattern for it. On the library prompt the 7 remaining notes change nothing in the output (the two loan-history methods are emitted as the same mechanical filter under either label; `return_loan` and the single-transaction rule are covered by the confirmed contract, the body gates and the acceptance test).

**Next step.** Each note should say what the generator did with the method (mechanical, delegated, or written by the model and checked by the gates) and whether the output is affected.

**Rule.** No note is silenced by adding a pattern that changes nothing.

## 2. Type hints are not provided everywhere

**Open.** The prompt asks for type hints throughout. A scan of the final library output found 110 functions, 48 without a return annotation and 100 parameters without an annotation. By file: `store.py` 27 of 28 functions and 57 parameters, `cli.py` 17 of 17 functions and 29 parameters (both come from fixed templates in the kernel, not from the model), `repositories.py` 1 function and 6 parameters, `services.py` 3 functions and 8 parameters (module helpers such as `_atomic` and `_holds`). The signatures of the domain methods are annotated.

**Next step.** Annotate the store and CLI templates and the emitted helpers, and add a scan to `tests/e2e_library_acceptance.py` so it stays met.

## 3. A shared verb is lost in the contract proposal

**Open.** For `return_loan` the confirmed contract has the `return_date` and copy effects but no `status = 'returned'` effect. The description "Sets return_date to today, status to 'returned', and ..." is split at the comma, and the second clause has no verb of its own, so it proposes nothing. The generated body sets the status and acceptance checks it, so the behavior is right today. The contract does not guard it, though: a body that forgot the status would pass the gates.

**Next step.** Let a verb carry across a comma-separated list in `review_contracts._propose`, with a test, then re-review the affected contracts.

## 4. Error messages requested by the prompt

**Open.** Error message wording is deliberately not asserted, because the prompt does not ask for it. Where a prompt does request a specific message or error, it should be verified. Today the acceptance test checks error names only where the fixture names them (`AlreadyReturnedLoanError`) or by a general marker (`NotFound`, `Negative`).

**Next step.** When a prompt states required messages, add them to the acceptance fixture and assert them.

## 5. Optional, larger: emit service bodies from the confirmed contract

**Open.** The confirmed contract (effects, creates, preconditions, order) already holds what `create_loan`, `return_loan` and `renew_membership` do, yet the model still writes those bodies and the gates check them. Emitting them mechanically from the contract would remove the model from them.

**Depends on** point 3: a body written from today's `return_loan` contract would drop the status.

## 6. Acceptance tests exist for the library and expenses prompts only

**Open.** `tests/e2e_library_acceptance.py` (passes 17) and `tests/e2e_expenses_acceptance.py` (passes 13 of 13) are written by hand for their prompts: its commands, fixture data, generated class and method names, and error markers all come from that prompt and its extraction. The `inventory` and `hello` outputs have no acceptance test, so for them a clean readiness check is the only evidence, and it does not run the generated program.

**What is reusable.** The scaffolding (running the generated CLI in fresh processes, inspecting SQLite, never editing a generated module), the sensitivity check (running a test against a deliberately broken copy of the generated package), and the line tracer that measures which model-written lines a test executes.

**Next step.** Either write an acceptance test for each prompt that ships with the project, reusing that scaffolding, or build a generic harness that derives scenarios from the requirements. The second ties each requirement sentence to a design item and a test, as `doc/checks-coverage-and-gaps.md` describes. It is the larger piece of work, and nothing of it exists yet.

## 7. Speed (body prompt reordering implemented)

**Partly addressed.** A complete library run takes about 17 minutes: extraction is decode-bound (about 10 min) and generation was prompt-bound (about 7.5 min, now about 5 min with the reordered prompt). The measurements, the ideas ranked by expected gain, and what not to do are in [`doc/speed.md`](speed.md).

The body prompt now puts the shared rules, references, API, requirements and module text before the method-specific block. On the expenses prompt a regeneration fell from about 4 minutes to about 2 minutes, and the next body reuses about 3.6k of its 3.8k prompt tokens. `scripts/start_llama_server.sh` leaves `--cache-ram` unset (llama-server's default applies). Speculative decoding with the Qwen3-0.6B draft was measured and is slower on this 16 GB M1 Pro (extraction 409.5 s vs 397.5 s; body generation 156.8 s vs 125.9 s), so it is opt-in with `SPEC=1`. Every body answer now records its wall, prompt, cached-prompt and decode time in `llm_stub_answers.json`.

**Next step.** Cache model answers by prompt so unchanged reruns take seconds; use the new per-body timings to cut the five library repair asks, then re-try speculative decoding only with a different draft model or tuning.

## 8. `main.py` stops at the review questions

**Open.** By default `main.py` extracts unreviewed, and a prompt that leaves open questions stops at readiness with KO (for example `prompts/prompt_expenses.txt`: 4 blockers, three of them `open_human_review`). `--review` answers them, but it replaces the spinner with the extractor's raw output.

**Next step.** Keep the spinner and show only the question when one is asked, then hide the output again.

## 9. Nested command paths (expenses): done for two-word and three-word paths

**Mostly addressed.** `prompts/prompt_expenses.txt` nests three levels (`expense category add`, `expense report monthly --month`, `expense recurring detect`). The surface model stays (command, subcommand), but a subcommand name may now be a path such as `category add`; the generated CLI nests click groups (or chained argparse sub-parsers) from it.

**How it works.**
- `uses_paths(spans)` in `kernel/extraction/command_lines.py` turns path mode on only when at least two command lines share a program word and some line has three or more words after it. The library and inventory prompts never trigger it, so their behavior is unchanged (checked offline by hashing attribution, prompt block, components grammar, generated `cli.py` and readiness against a pristine worktree, and by the unit tests).
- In path mode the prompt shows the model each command line already filed (`command expense, subcommand category add`), the grammar accepts a path name, and `repair_nested_paths` (`kernel/extraction/repairs.py`) rebuilds the tree from the requirement lines deterministically, because the 4B model flattens the nesting and invents flags. It reuses the model's own typed flat-leaf flags.
- The consistency checks resolve the longest path, report a missing path line as `missing_command`, and use the first word on every line as the program name. The binder scores adapters by the path's nouns.
- Tests: `tests/test_surface_paths.py`.

**Still open.** Paths are limited to three words. A true N-level model was not built.
