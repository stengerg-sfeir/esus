# ESUS library generation fix plan

> **Archived on 2026-11-03.** All five steps are complete and the acceptance test passes (see the step 5 status). This file is kept as the record of what was fixed and why. Work that is still open lives in [`doc/open-points.md`](../open-points.md).

## Goal

Fix ESUS so its extraction, human-review, readiness, and code-generation stages can produce a usable library application. Fix ESUS and its test harness; do not patch `out/library/generated/` by hand. Generated code is an output to inspect and exercise, not the location for the fix.

The final acceptance check must run end to end from the requirements prompt through extraction, human decisions, generation, and behavior against a temporary SQLite database. Unit tests remain useful during implementation, but a green unit suite or readiness probe alone is not acceptance.

## Current baseline

- `out/library` has architecture documents and a generated multi-module package. The read-only readiness probe reports 0 blockers, 15 risks, and 0 open ties.
- The requirements ask for `--author-id` and search by author, but the extracted `Book` has no author relationship. Its create adapter drops `--author-id`; generated author lookups compare the author ID with `Book.id`.
- The `--available-only` surface decision changes a presence flag into an integer-valued option.
- The generated `borrow_book` supplies `published_year + 10` as a date. The repository then calls `.isoformat()` on that integer. `BookRepository.update` also rejects zero available copies, preventing a borrow of the final copy.
- The generated `search_books` contains a comment saying one of its calls is incorrect, treats an ISBN miss as an exception, combines a list with a single model, and places mutable dataclass instances in a set.
- The saved `return_book` contract rejects overdue loans, contrary to the requested return effects. The review tool currently proposes primary-key mutations for `BookRepository.update` and `LoanRepository.update`.
- The LLM body path accepts code after syntax and API-shape checks; that does not establish that the body fulfills its behavior. The current generated bodies demonstrate this gap.

These findings make the current output a diagnostic baseline, not a passing acceptance result. Preserve the existing working tree and recorded decisions while preparing a fresh test output directory.

## Fix sequence

### 1. Make the library fixture unambiguous [DONE]

Update `prompts/prompt_library_system.txt` so every behavior needed by the CLI is represented explicitly:

- [x] Add `author_id` to `Book` as a required foreign key to `Author.id`; define that each book has one author for this test.
- [x] Add the minimal author CLI action needed to create an author before adding a book, or supply an explicitly documented fixture bootstrap through the generated application API. Prefer the CLI action so the acceptance path is user-visible.
- [x] Define `--author` as an integer author ID and `--available-only` as a no-value boolean flag.
- [x] Define search as case-insensitive substring matching across book title, author name, and ISBN, with duplicate books returned once.
- [x] Define a 14-calendar-day loan period from the loan date. Keep the rule in the service behavior, rather than silently inventing it in a repository default.
- [x] Define zero available copies as valid; reject only negative copy counts.
- [x] Clarify overdue behavior and repeat returns as specified in the human-answer section below.
- [x] Use optional ID annotations (`int | None`) when the default is `None`; preserve SQLite auto-increment and the requested uniqueness and cascade rules.

Keep these clarifications in the fixture prompt for repeatable tests. They should not be added only to a generated file or hidden in a test patch.
*Status: Completed. `prompts/prompt_library_system.txt` updated with explicit behavior; command extraction verified by `tests/test_command_lines.py`.*

### 2. Correct extraction and decision handling [DONE]

Fix ESUS so its intermediate documents and saved human decisions represent the clarified prompt:

- [x] Extract `Book.author_id` and its FK, and keep that field through model, schema, repository, adapter, and CLI generation.
- [x] Bind `book add --author-id` to the `author_id` create parameter. Do not silently discard a required CLI option.
- [x] Bind `book search` to the cross-field search service. Bind `book list --author` to the author-ID filter. Bind `--available-only` as a boolean presence flag mapped to a minimum of one copy.
- [x] Correct the human-review proposal logic so repository update IDs are lookup keys, not proposed write effects. A review should offer mutable model fields and their valid sources, never `Book.id = book_id` or `Loan.id = loan_id` as the update.
- [x] Record the complete behavior contracts: borrowing creates one loan and decrements one copy after validating availability; returning sets the date/status and increments one copy exactly once; both multi-write operations are atomic.
- [x] Ensure a stale or conflicting saved decision cannot silently override the clarified prompt. In the test output, replace the old `available_only` integer route and the overdue-return rejection contract with the answers below. Leave the user's existing `out/library` decisions untouched until running that test in isolation.
- [x] Make surface review distinguish an actually dead option from one whose target model field or adapter was omitted upstream. It must not recommend dropping `--author-id` when the repaired architecture defines the field and method parameter.
*Status: Completed. Verified across `kernel/extraction/repairs.py`, `kernel/codegen.py`, `review_contracts.py`, and `review_surface.py`, with passing unit tests in `test_contracts.py`, `test_surface.py`, and `test_repairs.py`.*

### 3. Strengthen readiness and body acceptance [DONE]

Improve ESUS checks so a structurally consistent document set cannot pass while its declared interface is unusable:

- [x] Check that every required CLI option has exactly one effective adapter mapping, and flag required options that are parsed but ignored.
- [x] Check option syntax against type: a no-value flag must be boolean; a value option must declare a value type. Check that boolean flags use an explicit supported transform when the target parameter is numeric.
- [x] Check all adapter targets against repository/service signatures and model fields, including create and update payloads.
- [x] Check that author search has an actual Book-to-Author relationship and that its generated filter uses that FK.
- [x] Check update contracts for primary-key writes, invalid state transitions, missing required side effects, and contradictory conditions.
- [x] Require generated bodies to satisfy their method contract and declared effects. Reject unresolved reasoning/comments such as “this is incorrect,” arithmetic integers assigned to date fields, impossible return shapes, and invalid set/deduplication operations on mutable models.
- [x] Keep syntax/compile validation, but report an LLM body as provisional until it passes the end-to-end behavior checks. A body being “written” must not be represented as equivalent to a correct implementation.
- [x] Treat unresolved business behavior as an explicit human question or a visible stub. Do not guess a date policy, invent an error rule, or silently mark a body complete.
*Status: Completed. Implemented in `probe_readiness.py` (`generation_surface_findings`, `relation_filter_findings`, `contract_record_findings`, `open_review_findings`) and `generator.py` (`_body_complaints`, `_date_assignment_complaints`, `_store_operator_complaints`, null-return threshold checks), verified by `test_generator.py`.*

### 4. Human questions and expected answers for the library acceptance run

Ask these questions in the review flow before generation. Store answers in the isolated test output with the current requirements hash. The answers below are the expected test decisions; they are explicit human choices and may intentionally clarify or extend the original prompt.

1. **How are books related to authors?**  
   **Expected answer:** One author per book. Add a required `Book.author_id` FK to `Author.id`; use the declared cascade-delete policy. `book add --author-id` is required.

2. **How can the CLI create the author needed by `book add`?**  
   **Expected answer:** Add `author add --name --birth-year [--biography]` to the CLI for this test. This is an explicit human-approved addition to the requested surface.

3. **What does `book list --author` accept?**  
   **Expected answer:** An integer Author ID. Filter on `Book.author_id`, not on `Book.id` or an author name.

4. **How should `--available-only` behave?**  
   **Expected answer:** It is a boolean flag with no following value. When present, return books with `available_copies >= 1`; when absent, do not apply the filter.

5. **What does `book search --query` match?**  
   **Expected answer:** Case-insensitive substring match against title, author name, or ISBN. Return each matching book once, including when it matches more than one field. An ISBN miss is an empty result, not an exception.

6. **What is the loan period?**  
   **Expected answer:** A loan is due 14 calendar days after its loan date. The service computes and passes a date/datetime value; the repository does not derive it from `published_year`.

7. **When is a loan overdue, and may it be returned?**  
   **Expected answer:** It is overdue when `due_date < today` and `return_date` is null. An overdue loan may be returned. Returning it sets `return_date` to today, changes status to `returned`, and restores one available copy.

8. **What should happen on a repeated return?**  
   **Expected answer:** Raise `AlreadyReturnedLoanError`; do not change the loan or inventory a second time. Add this error to the declared error set.

9. **Is zero a valid available-copy count?**  
   **Expected answer:** Yes. Zero is valid after the last copy is borrowed; reject only values below zero.

10. **How should overdue status be represented without a background scheduler?**  
    **Expected answer:** For this test, derive overdue status from the due date and null return date when reading/querying loans. Keep the persisted status `active` until return, then `returned`. This is a human-approved clarification of the original status wording.

11. **What happens if one write in borrow/return fails?**  
    **Expected answer:** Roll back the whole operation. Loan creation and copy decrement, and loan return and copy increment, each run in one transaction.

### 5. Final end-to-end acceptance test [DONE]

Run the final test from a clean temporary output directory. Do not reuse the current `out/library` artifacts or manually edit generated modules. Use the real configured model/server for extraction and body generation; supply the expected human answers above through the attended review flow. A mocked LLM, a direct generator unit test, or a readiness-only run does not satisfy this acceptance step.

The test chain is:

1. Run `extract_arch.py` against `prompts/prompt_library_system.txt` with `--chat` and the configured model/server, writing to a new temporary output directory.
2. Answer each listed human question with its expected answer; save the resulting records in that temporary output only.
3. Run the consistency/readiness checks. Fail if any command is unbound, any required option is ignored, any adapter references an undeclared field, or any human question remains open. Print residual classification risks for review.
4. Run `generator.py` on that output with body generation enabled and exact method context. Keep the complete generation log and raw body answers as test artifacts.
5. Run the generated CLI against a temporary SQLite database. Create an author, member, and book; verify the FK, unique ISBN/email, default copies, author filter, boolean available-only flag, and cross-field search.
6. Borrow the last available copy. Verify exactly one loan exists, the due date is 14 days after the loan date, the copy count reaches zero, and a second borrow fails without partial writes.
7. Set up an overdue loan in the temporary fixture, list it as overdue, return it successfully, and verify status/date/copy count. Return it again and verify the declared error and unchanged stock.
8. Reopen the SQLite database and verify persisted state and cascade behavior. Do not edit the generated package to make assertions pass.

Acceptance is met only when the full chain completes and the assertions pass on code produced by ESUS. Preserve the extraction output, review answers, generation log, raw LLM answers, and test results together so failures can be traced to the prompt, review record, readiness gate, or body generator.

*Status: Completed on 2026-11-03. `tests/e2e_library_acceptance.py` reports **PASS: 17 end-to-end checks** on a clean run: extraction without `--repair`, a complete generation with no reused bodies, and the real model. The unit suite passes (907 tests). The first pass had 7 checks; a requirements review of the passing output found `member list` broken and an extra `return loan` command, so more checks were added and the run repeated from a fresh extraction; the checks that had only been done by hand were then added too, and finally the prompt-named methods the CLI does not reach (see below) (see the requirement coverage section below). Everything is kept in `/private/tmp/esus-library-e2e-5/`: documents, `answers.log` (every answer and the reason for each skip), `generation.log`, `llm_stub_answers.json` (raw answers, refusals and equivalence verdicts), `e2e_results.json` and the archived earlier attempts.*

**Result of the clean run.** Seventeen checks pass: creation with FK/uniqueness/default copies; author filter, `--available-only` and deduplicated cross-field search; duplicate ISBN/email rejection; `member list` lists everyone and `--active-only` only the active (against a member made inactive in the fixture); borrow rolled back when the inventory write fails; 14-day due date, final-copy borrow and no partial second borrow; derived overdue status, late return and duplicate-return protection; `member history` lists that member's loans only; no subcommand beyond the requested CLI surface (`return loan` is rejected); rejected input (unknown author, member, book or loan, negative copies) is named and changes no row, and `membership_date` defaults to today; persistence and cascade after reopening the database; then two more on a separate database through the CLI (a loan due exactly today is not overdue while one due yesterday is, `--biography` is stored, every table auto-increments its id; and a return rolls back its loan update when the inventory write fails, as a borrow does); then, called in-process through the generated package's own wiring on a separate database: create/read/update/delete on all four repositories, the repository finders (books by author, stock filter, active and inactive members, active and overdue loans, member and book loan history), and `renew_membership` (toggles `is_active`, rejects an unknown member); and one check labelled EXTRA for the service methods the prompt does not ask for (below). In the final run the body gates refused two model bodies (an unsupported `is` operator, a `dict.fromkeys` over mutable models) and the model corrected each on the repair ask; earlier runs also had a confirmed create called twice and an indentation error caught. Those differences came from changes made to the code and the prompts between runs, not from sampling: see the reproducibility note below. The model wrote 24 bodies (28 before the `READ_ONE_BY_ID` pattern below).

**Defects the acceptance run exposed, now fixed in ESUS** (each has a test that fails without the fix). Steps 2 and 3 were marked done before these existed; a real run found what unit tests had not.

- Extraction/readiness: `BOOL_TO_ONE` onto a bool parameter is repaired to `DIRECT`, and the `--repair` path passes `services` like the pipeline. A repository `create` that describes a required field its parameters omit gets that parameter, and readiness (`create_field_unreachable`) blocks any required field no create can set (`Loan.due_date`, `Loan.status`).
- Contracts: the review proposed `create_<entity>`/`update_<entity>` only, so with plain `create`/`update` repositories every service contract lost its confirmed create and save, and a two-write method was not wrapped in a transaction (`_repo_call`). Two contract kinds were added in the same domain-neutral vocabulary: `reads` (a search must read the related model's field, proposed from the foreign keys and the method's own words) and `derives` (a value the returned records carry in memory, never saved).
- Generator, mechanical code: `update` looked a record up by all its parameters, including the new values, so the last copy could never be borrowed; the store compared stored dates with ISO text, so `le`/`ge` raised `TypeError` and `eq` never matched; the store gained strict `lt`/`gt` (overdue is `due_date < today`).
- Generator, CLI: an absent no-value flag parses as `False` and was passed on, so a body reading `False` as "inactive only" made plain `member list` print nothing. Both CLI backends now skip a flag that was not given, and the method's own default applies. This was found by checking the passing output against the prompt, not by the first acceptance run, which never called `member list`.
- Surface review: a subcommand repeating its own parent's flags (`return loan --loan-id` beside `return --loan-id`) was invented by the extraction and never asked. The review now asks it as a redundant subcommand when both nodes take exactly the same flags and no requirements line names the pair; dropping it keeps the parent. A pair already asked as a duplicate of a top-level command (`borrow book`) is not asked twice. Nothing is deleted unasked, and on the other existing outputs the check asks nothing.
- Pattern catalogue: the catalogue had no pattern for reading one record by its key, so the four `read_*_by_id` methods were claimed as `READ_ALL`, refused by the shape check (a list is not an entity), reported as missing patterns and left to the model. `READ_ONE_BY_ID` (repository layer, returns an entity) is added; `plan_method` reads it as a mechanical read-one whatever the method is called; a service method with that plan now delegates to the entity's repository `read_one` (`_read_one_target`, same normalized parameters and return type, never into a guard or stub); and the classifier may correct a refused claim into a pattern that returns one record, as it already could into one that returns a list (booleans, scalars and mappings stay excluded). With the real classifier all four methods are chosen directly at confidence 0.93 to 0.999, and they are emitted mechanically.
- Generator, body gates: a guard is accepted when it is the contract's text or when a model judge says it means the same (verdicts recorded; anything but a clear yes refuses); early preconditions now give the model a literal guard line; return types are resolved through the repository the call goes through; a confirmed create must be called exactly once; unsupported store operators are caught when criteria are built through a named list, with a hint for synonyms; mutable models are refused in `set`, `frozenset`, `dict.fromkeys` and set/dict comprehensions.

**Caveats.**

- The attended review answers were replayed by a script from decisions already taken and logged, not typed live; it stops at any prompt it does not recognize. The extraction summary says "unreviewed" because stdin was a pipe, not a terminal.
- The model was Qwen3-4B-Instruct (Q4_K_M) through `llama-server`; the plan names no configured model, and results will differ with another one.
- *Reproducibility, measured:* three complete runs on the same code (the earlier one, then two after stopping and restarting the server with a cold prompt cache) produced byte-identical extraction documents, review records, raw model answers and generated modules. The only difference was the output directory's name, which ESUS embeds as the generated program's name (`DEFAULT_DB`, the click group, a comment in `__init__.py`); after normalizing it the three runs are identical. Output changes when the code, the catalogue, a gate message or a neighbouring method body changes, because the generation prompt contains the module text. This holds for the same model, server flags, context size and hardware; another llama.cpp build or machine may differ in floating point.
- Every LLM body remains tagged provisional. The acceptance test is what verifies them, and only for the paths it exercises.
- Ten review questions were skipped on purpose (offers to drop required flags such as `member add --name`, the ISBN-format condition, and a return-time error asked on borrow). Reasons are in `answers.log`.
- The polarity check for guards is structural (`is None` is not recognised as the negation of `is not None`), so an inverted guard in another form depends on the model judge.
- Repair asks sometimes need the exact complaint to succeed; a smaller model may leave stubs where a stronger one would not.

**Requirement coverage (what "compliant with the prompt" can and cannot mean today).** Passing acceptance is not the same as meeting every requirement; this is the honest split.

- *Verified by the acceptance test, required by the prompt:* the prompt's repository CRUD and finders and `LibraryService.renew_membership` (items 5-9), which have no CLI command and are checked by calling the package directly; the CLI surface itself (nothing beyond the requested commands); models and constraints (unique ISBN and email, default copies, FK with `CASCADE`); every command in the requested CLI (`author add`, `book add/list/search` with `--author` and `--available-only`, `member add/list` with `--active-only`, `member history`, `borrow`, `return`, `overdue`); borrow and return effects, atomicity, the 14-day due date, derived overdue status, `AlreadyReturnedLoanError`, not-found errors for author, member, book and loan, rejection of negative copies, the `membership_date` default, no partial writes on rejected input, persistence and cascade.
- *Extra service methods, not requested by the prompt:* the prompt's `LibraryService` has five methods (`borrow_book`, `return_book`, `get_overdue_loans`, `renew_membership`, `search_books`). The extraction also generated `update_*`, `delete_*`, `read_*_by_id` (now emitted mechanically as delegations to the repositories' `read_one`), `read_all_authors`, `read_all_loans` and `LoanService.get_book_loan_history`. They are not requirements. The acceptance test still exercises them on the happy path (update persists, delete removes and cascades, reads return the record or report absence) and reports them as a separate check labelled EXTRA, so a pass there is never read as prompt compliance; their error behavior is not asserted because the prompt defines none.
- *Requirement not met, measured:* "use type hints throughout". A scan of the final output finds 110 functions, 48 without a return annotation and 100 parameters without an annotation. By file: `store.py` 27 of 28 functions and 57 parameters, `cli.py` 17 of 17 functions and 29 parameters (both come from fixed templates in the kernel, not from the model), `repositories.py` 1 function and 6 parameters, `services.py` 3 functions and 8 parameters (module helpers such as `_atomic` and `_holds`). The signatures of the domain methods are annotated. Not fixed yet.
- *Not verified:* "clean architecture" and separation of concerns (the package is split into `models`, `repositories`, `services`, `store` and `cli` modules, but nothing judges the separation); ISBN format validation is deliberately absent (the prompt defines none). No CLI command was added for anything the prompt does not list.
- *Sensitivity of the new checks:* each prompt-required check was run against a deliberately broken copy of the generated package (renew_membership a no-op, each finder returning every row, `get_inactive_members` returning nothing, repository delete a no-op) and failed with a specific message; the EXTRA check failed on a no-op `update_book`. The behavior checks were likewise run against a copy where a loan due today counts as overdue and a copy where `return_loan` is not atomic, and both failed with specific messages.
- *Surface deviation, resolved:* the extraction used to add `return loan --loan-id` next to the requested `return --loan-id`. The redundant-subcommand question removes it, and the acceptance test now asserts that `return loan` is rejected. The CLI surface of the final run is exactly the prompt's list plus `author add`, which the fixture adds on purpose.
- *Open readiness risks:* 7 non-blocking risks remain unreviewed, down from 9 (the four `read_*_by_id` methods are closed by `READ_ONE_BY_ID`). What remains: `return_loan` and the single-transaction invariant fit no pattern (gaps, written by the model and checked by the gates); `get_book_loan_history` and `get_member_loan_history` were first claimed as an aggregate, corrected to a filter, and sit near a tie between `FILTER_BY_FIELD` and `FILTER_WITH_PAGINATION`, so the choice may differ when the catalogue, the prompt or the model changes. Adding the new pattern shifted the classifier's probabilities, which is why `get_member_loan_history` now carries notes it did not before; its result is unchanged. These notes explain how a method was generated (how sure the classifier was, whether two labels were close, whether the catalogue has no pattern); they are not defects, and none changes the output here: the two loan-history methods are emitted mechanically as the same filter under either label, and `return_loan` and the transaction rule are covered by the confirmed contract, the body gates and the acceptance test. They are deliberately not silenced by adding patterns that change nothing.

## Expenses acceptance (2026-11-04)

`tests/e2e_expenses_acceptance.py` went from 3 of 13 to 13 of 13 on a fresh, reviewed expenses run. The fixes are domain-neutral where the defect was in the generator, and the library acceptance still passes 17 of 17.

- **Period labels:** `month`/`year` fields declared as text (`month (str like "2024-01")`, or an invariant saying `must be a string in the format 'YYYY-MM'`) are repaired from `date` to `string`; an `ISO_DATE` transform on a month/year flag becomes `DIRECT`.
- **Dates:** `ISO_DATE` now parses the value to `datetime.date`; service filter composition normalises both the read dataclass's date and the criterion with `_filter_value`, so a date range compares like with like.
- **Composite unique:** `UNIQUE(category_id, month)` (or "a unique combination of ...") is emitted as a table-level constraint; fields in the pair are no longer also marked unique on their own. The store template learned `unique_together`.
- **Updates:** a method taking `data: dict[str, any]` gets its mapping merged into the patch, so `category update --name` changes the name; the CLI groups sibling flags into that dict. A gap-classified `update` is read as an update, and a composite key identifies the record, so `budget update --amount` no longer searches for the new amount.
- **Create defaults and return values:** a create port declared `-> int` returns the new key; non-null enum fields default to their first documented value and reject other spellings; non-null booleans without a documented default default to `False`. An omitted optional create date defaults to today.
- **Missing budget:** a `read_one` whose declared error does not belong to its entity returns `None` instead of raising the wrong not-found error, so an expense with no budget is still stored.
- **Post-insert checks:** a requirement that says "after insertion" permits a raise after the create, rejects a pre-create budget check, and tells the body writer that the stored record is intended.
- **Body gates:** the generator now names a repository method called on the wrong repository, a field dict passed positionally into a scalar parameter, and a dataclass mutated without any repository update. These caught the wrong `find_expenses_by_category` owner, the recurring update, and the unsaved `is_recurring` flag.

## Open points

Moved to [`doc/open-points.md`](../open-points.md): clearer readiness notes, type hints, the shared-verb gap in the contract proposal, error messages requested by a prompt, and emitting service bodies from the confirmed contract.

## Completion criteria

- The clarified prompt and human answers produce the intended intermediate documents and CLI bindings.
- Readiness catches the current author-link, dead-option, and type-shape defects before generation.
- The generator does not accept a syntactically valid but behaviorally contradictory LLM body as complete.
- The end-to-end acceptance test passes without hand-editing generated code.
- Existing user changes and recorded decisions are preserved outside the isolated test output.

All five criteria are met as of 2026-11-03 (see the step 5 status). The existing `out/library` artifacts and decisions were not touched; the final run used `/private/tmp/esus-library-e2e-5/`.
