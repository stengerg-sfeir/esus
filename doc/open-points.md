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

## 6. Acceptance tests exist only for the library prompt

**Open.** `tests/e2e_library_acceptance.py` is written by hand for the library prompt: its commands, fixture data, generated class and method names, and error markers all come from that prompt and its extraction. The `expenses`, `inventory` and `hello` outputs have no acceptance test, so for them a clean readiness check is the only evidence, and it does not run the generated program.

**What is reusable.** The scaffolding (running the generated CLI in fresh processes, inspecting SQLite, never editing a generated module), the sensitivity check (running a test against a deliberately broken copy of the generated package), and the line tracer that measures which model-written lines a test executes.

**Next step.** Either write an acceptance test for each prompt that ships with the project, reusing that scaffolding, or build a generic harness that derives scenarios from the requirements. The second ties each requirement sentence to a design item and a test, as `doc/checks-coverage-and-gaps.md` describes. It is the larger piece of work, and nothing of it exists yet.
