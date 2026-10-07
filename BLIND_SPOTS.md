# Checker blind spots — a review of the generated documents

Scope: all seven prompts, every generated document, read against
`prompts/prompt_*.txt` and against the checker's actual rule set.

The checker could emit **20 rules** in three severities when this review began; it emits **37**
now, because §1–§5 have been closed (each is marked below), §9.24 added three for the CLI surface
and the error registry, and §9.26 added five more — four of which are the only rules that can see
a document disagreeing with the *requirements* rather than with another document. §9.27 added no
rule: it closed the defect §9.25's surface checks were reporting — an option repeating a
subcommand's name — inside the grammar, so `invalid_value` (that case) can no longer fire.

```
errors   malformed_document missing_document missing_directory unexpected_shape
         invalid_value invalid_identifier unsupported_value duplicate_entry
         empty_section class_name_entity missing_primary_key no_mapping
         primary_key_mismatch
warnings unknown_reference name_variant unresolved_adapter_target
         inconsistent_adapter nullable_primary_key placeholder_value no_repository
         inconsistent_facade      ← added, §9.24: a parser with no arguments, or arguments with no parser
         contradictory_raise      ← added, §9.24: a create-like method claiming it cannot find what it creates
         misplaced_field          ← added, §9.26: an adapter field sent to a parameter that is not its own
         mismatched_transform     ← added, §9.26: a transform that does not fit the field it is applied to
         missing_command          ← added, §9.26: a command the requirements name and the surface lacks
         unreachable_error        ← added, §9.26: a not-found error nothing raises, while its reader exists
         duplicate_error_subject  ← added, §9.26: two error types naming one missing record
         inconsistent_interface   ← added, closes §1
         missing_parameters       ← added, closes §2
         unmet_crud_operation     ← added, closes §3
         non_unique_primary_key   ← added, closes §4
         inconsistent_invariant   ← added, closes §4
         low_confidence           ← added, closes §5
notes    empty_section
         unused_error             ← added, §9.24: a declared error type no method raises
         missing_pattern          ← added, closes §5
         narrow_margin            ← added, §5: the top two answers were too close to call
         corrected_claim          ← added, §9.19: an impossible pattern was refused and a possible one recorded
```

Every section below began as a defect that passed all 20 original rules. Each entry gives the
evidence, the rule that did not exist, and why the checker structurally could not see it — and
now also what was done about it.

**Status: §1, §2, §3, §4 and §5 are closed at BOTH ends.** First the checker was given the rules,
which made the defects visible — `0 error(s), 22 warning(s), 7 note(s)` at that point. Then the
extractor was fixed so it stops producing them, and the seven prompts now re-run to
**`0 error(s), 1 warning(s), 55 note(s)`** — the one warning is library's `missing_command`
(the requirements name `book search`; the surface lacks it), and the notes are 19 `unused_error`,
13 `narrow_margin`, 10 `missing_pattern`, 3 `corrected_claim`, 2 `low_confidence`, and the rest
`empty_section`. The six content contradictions an earlier run produced — `contradictory_raise`,
`duplicate_error_subject`, `unreachable_error`, `mismatched_transform` — are **removed in the
pipeline by a deterministic repair pass** (§9.28), not passed over; the pass only deletes or
redirects a value the same document already contradicts, and never invents one. The surface's
own defect was closed in the grammar (§9.27).
The notes moved 11 → 29 when
`missing_pattern` began reporting every gap instead of deleting the answer, back to 21 once the
rule/schema tag stopped field declarations reaching the classifier, to 20 when the read shapes were
completed and the runner-up recorded, to 28 when the catch-all became `UNKNOWN` and the attribution
was checked against each method's signature, to 39 when the margin stopped being measured against
the model's own claim and the **domain** stage began reporting too (§9.23), and to 44 when the error
registry began declaring types no method raises (§9.24) — the shape of the number is the history of
the work. Of the 10 `narrow_margin`, 4 are step 1 and 6 step 2. The 6 `missing_pattern` notes are 4
missing shapes, and one gap appears twice: read one record by something other than its primary key
(`read_category_by_name`, `read_budget_by_category_and_month`), a write that returns the entity it
wrote (`add_expense`, `assign_wine_to_location`), an export returning `bool` (`export_to_csv`), and
a threshold-filtered collection read (`find_low_stock_products`). Every rule's outcome:

| rule | severity | closes | fired when added | now |
|---|---|---|---|---|
| `inconsistent_interface` | warning | §1 | 10 | **0** |
| `missing_parameters` | warning | §2 | 12 | **0** |
| `unmet_crud_operation` | warning | §3 | 6 | **0** |
| `non_unique_primary_key` | warning | §4 | 1 | **0** |
| `inconsistent_invariant` | warning | §4 | 3 | **0** |
| `unknown_reference` (pattern ids) | warning | §5 | 3 | **0** |
| `low_confidence` | **note** | §5 | 5 | **0**, reported not counted |
| `missing_pattern` | **note** | §5 | — | **6**, reported not counted; 6 gaps are 4 missing shapes |
| `narrow_margin` | **note** | §5 | — | **10** (4 domain, 6 pattern), reported not counted |
| `corrected_claim` | **note** | §9.19 | — | **1**, reported not counted |
| `unused_error` | **note** | §9.24 | — | **18**, reported not counted |
| `inconsistent_facade` | warning | §9.24 | — | **0** |
| `contradictory_raise` | warning | §9.24 | 4 | **3** — the prompt named the mistake, and a later run still produced three (§9.27) |

Six rules were added to name the defects and five source changes removed them. The seventh entry
is a **correction of my own rule**, not a source fix: three `unknown_reference` findings flagged
`CUSTOM_DOMAIN_LOGIC`, which turned out to be the classifier's deliberate "matches no standard
pattern" option rather than a defect — see §5. And `low_confidence` moved from warning to note:
the value is the product of two softmaxes so it is structurally low, and the checker cannot tell
a low-confidence-but-correct classification from a wrong one, exactly as it cannot tell an empty
section from a missing one.

**The rules are not tuned to stay quiet.** Run against `backup/out_pre_grammar_fix`, the same
rules report **9** `non_unique_primary_key` against 1 today, alongside the three original
`primary_key_mismatch` errors — so as the extractor improved, each defect's count fell.

Five source changes removed the warnings, and the content-volume table in `FIX_PLAN.md` §9.14 is
what shows they removed defects rather than content — every document was counted before and after,
which is how `cli_tool`'s eleven invented bookshop invariants and a repository-collapse regression
were both caught. The one document that is genuinely thinner is the adapter list, and the checker
cannot judge whether that is a loss: see §8.

256 unit tests cover the rules and the extractor fixes (`tests/test_checker_rules.py`,
`tests/test_interfaces.py`, `tests/test_checker_blind_spots.py`,
`tests/test_invariant_kinds.py`, `tests/test_grammar_preflight.py`,
`tests/test_truncation_retry.py`, `tests/test_narrow_margin.py`,
`tests/test_pattern_shapes.py`, `tests/test_dedupe.py`,
`tests/test_data_model_grounding.py`, `tests/test_facade_and_errors.py`,
`tests/test_repairs.py`).

Reproduce with `python3.12 check_consistency.py --dirs <name>:out/<name> --all-findings`; the
pre-fix numbers quoted are from the runs recorded in `FIX_PLAN.md` §9.2.

---

## 1. The two documents that describe the same interface disagree — **CLOSED (extractor)**

**Extractor fix:** `kernel/extraction/interfaces.py`, called from `_step_persistence`. Step E
owns every repository interface it declares; step H's repository for the same name adopts E's
methods verbatim and keeps what only H produces — the table, the primary key and the indexes.
Repositories E does not declare (60's) keep step H's own method set. Measured: adopted in
inventory (2 interfaces), gui (2), expenses (3), library (4); 60 correctly untouched.

**Checker rule:** `inconsistent_interface` (warning),
`kernel/consistency/checks_interfaces.py`, called from `check_architecture_layer`. It compares
the method set of every repository whose `persistence_ports` `interface_name` matches a
`service_contracts` `service_name`, using the checker's `normalize` so a `WineService` is never
confused with a `WineRepository`. This rule is what caught the defect; the extractor fix above
is what removed it.

**Measured:** 10 warnings — inventory 2, gui 2, expenses 3, library 3. 60 is silent and
correctly so: its `persistence_ports` repositories have no counterpart service, because 60's
services are named `CategoryService`, `CustomerService`, and so on.

**Severity: highest. This is the one a code generator would fall over.**

`service_contracts` holds repositories as services, and `persistence_ports` holds repositories as
ports. Both name them `XxxRepository`. Nothing relates the two documents. Measured:

| prompt | interface | `service_contracts` | `persistence_ports` |
|---|---|---|---|
| gui | `WineRepository` | create_wine, update_wine, delete_wine, get_all_wines, get_wine_by_id, get_wine_by_name | save_wine, update_wine_price, update_stock_quantity, get_wine_by_id, get_all_wines, get_wines_by_type, get_wines_by_country, get_wine_by_name |
| gui | `StorageLocationRepository` | create_location, update_location, delete_location, get_all_locations, get_location_by_id | save_location, update_location_capacity, get_locations_by_zone, get_locations_by_shelf, get_location_by_id, get_all_locations |
| inventory | `CategoryRepository` | 5 methods (add/get_by_id/get_by_name/get_all/get_products_by_category) | 1 method (`create`) |
| expenses | `CategoryRepository` | 7 methods | 4 methods (incl. `get_by_id`) |

For gui's `WineRepository`, `delete_wine` exists **only** in the service document; `save_wine`,
`update_wine_price`, `update_stock_quantity`, `get_wines_by_type` and `get_wines_by_country`
exist **only** in the persistence document. The adapter document validates against
`service_contracts`; the persistence document is what would be implemented. They describe
different classes under one name.

**Why invisible:** `check_interaction_adapters` resolves targets against `service_contracts`;
`check_persistence_ports` resolves `repositories[].entity` against `data_models`. Neither ever
compares `service_name` with `interface_name`, so the divergence is outside both resolution
graphs.

---

## 2. A method that provably needs arguments declares none — **CLOSED (extractor)**

**Extractor fix:** two parts. Most of the class disappeared for free once §1 was fixed, because
the parameters now come from step E's methods, which always declare them — inventory's
parameterless `create()` became `add_category(name, description, reorder_threshold)`. The
remainder was step H generating repositories E never declares (60's): `PERSISTENCE_SYSTEM` now
requires a method to declare the parameters its own name implies, and reserves the empty list for
a method that genuinely takes nothing. With both in place the seven prompts re-ran to
`0 warning(s)`, 60's `find_by_name()` included.

**Checker rule:** `missing_parameters` (warning), in `kernel/consistency/methods.py` so it
applies to every method block in both documents. A method that declares no parameters is flagged
when its name begins with a write verb (`create`, `add`, `save`, `insert`, `update`, `delete`,
`remove`, `set`) or ends in `_by_<key>` (`id`, `email`, `name`, `sku`, `isbn`, `title`, `code`,
`key`, `slug`, `number`). Aggregates are exempt, because "by X" there means "grouped by X":
`get_total_stock_value_by_category()` is complete as declared.

**Measured:** 12 warnings — inventory 2 (`create()` in both repositories), gui 3, expenses 2,
60 1 (`find_by_name()`), library 4. The rule is deliberately narrower than the prose below: it
does **not** flag `get_active_members()`, `get_overdue_loans()` or `get_books_available_only()`,
because a predicate or a default date in the name is not a missing argument. Those remain
judgement calls for the repair pass.

**Severity: high, and systemic — every one of the five domain prompts.**

`param-list` has minimum 0, so "no parameters" is always legal. Observed:

| prompt | parameterless methods in `persistence_ports` |
|---|---|
| inventory | `create()` in both repositories — a create with no fields |
| gui | `get_wine_by_id()`, `get_wine_by_name()`, `get_all_wines()`, `get_location_by_id()`, `get_all_locations()` |
| expenses | `get_by_id()` in CategoryRepository and ExpenseRepository |
| 60 | `find_by_name()`, `find_all()`; `find_all()` in four repositories |
| library | `get_book_by_id()`, `get_author_by_id()`, `get_member_by_id()`, `get_loan_by_id()`, `get_active_loans()`, `get_overdue_loans()`, `get_books_available_only()`, `get_authors_with_books()`, `get_active_members()`, `get_inactive_members()` |

`get_wine_by_id()` cannot know which wine; `create()` cannot know what to create. The **same
methods carry parameters in `service_contracts`** (`WineRepository.get_wine_by_id(wine_id)`), so
the parameters were lost only in the persistence document.

**Why invisible:** the rule is a minimum *count* check, and the minimum is zero. To catch this
the checker would have to reason about the *name* — a method whose name contains `by_id`, `by_`,
`find_all`, `create`, `update` or `delete` must declare parameters, and a `create`/`update` must
declare parameters drawn from its own entity's fields. The entity is known
(`repositories[].entity`), so this is checkable, not a judgement call.

---

## 3. `crud_services` operations that no method implements — **CLOSED (both ends)**

**Extractor fix:** the defect was architectural. Step D declares which operations an entity
supports; step E owns the repository interface; nothing carried the operations from D to E, so E
wrote "standard CRUD methods" from an adjective and every `delete` was lost.
`vocabulary.crud_requirements` now carries them forward into `prompts.requirements_block`, which
both step E and step H receive, and `CONTRACTS_SYSTEM` requires a method per listed operation.
Measured after the re-run: every demanded `create` and `delete` has a method, and the count is 0.
An over-correction along the way — repositories collapsing to exactly the listed operations — was
caught by comparing content volume and fixed by stating the list is a **floor, not a ceiling**.

**Checker rule:** `unmet_crud_operation` (warning), `kernel/consistency/checks_crud.py`, called
from `check_architecture_layer`. For each `crud_services` entry it collects the methods of the
matching repository (by `persistence_ports[].entity`) and of any service named for the entity,
then requires `create` and `delete` to have a matching prefix. `read_one`, `read_all` and
`update` are deliberately not checked — their prefixes are ambiguous — so the rule
under-reports rather than guesses.

**Measured:** 6 warnings, all `delete` — inventory's `Category` and `Product`, and library's
`Book`, `Author`, `Member` and `Loan`. Every entity that claims it can delete something has no
method that can.

`components.crud_services` declares which operations each entity supports. Nothing checks that
any method provides them.

- **inventory** declares `Category: [create, read_all, update, delete]` and
  `Product: [create, read_one, read_all, update, delete]`, but neither `CategoryRepository` nor
  `ProductRepository` declares an `update` or a `delete` — they hold `add_*`, `get_*` and the
  custom queries only. (This example predates the §1 fix, which changed the repository method
  count from 2 to 11 without adding the missing operations: the gap is real.)
- **60** declares `order_items: [create]` and `invoices: [create]` only, for entities whose
  requirements describe far more.

**Why invisible:** `_check_crud_operations` verifies each operation is in
`("create","read_one","read_all","update","delete")` — spelling only. The operations list and
the method lists are never compared.

---

## 4. A document contradicts another document — **CLOSED (both ends)**

**Extractor fixes:** `DATA_MODELS_SYSTEM` now sets `unique: true` on the primary key and on every
field the requirements say must not repeat, which removes inventory's `Product.id`. And step C is
now **chained on step B** — the plan's dependency table (§2.2) had said chaining here "adds
noise", and that was wrong: C was free to state `category_id must be nullable` against a model
declaring it not nullable. C now receives the data model and is told it is authoritative.
Measured: 0 findings for both rules.

**Checker rules:** `non_unique_primary_key` (warning), one line in
`kernel/consistency/checks_models._check_primary_keys` — a field that is both a primary key and
`unique: false` is self-contradictory. Measured: 1, inventory's `Product.id`. And
`inconsistent_invariant` (warning), `kernel/consistency/checks_invariants.py`, called from
`check_domain_layer` — it matches `<field> must be unique` and `<field> must be nullable` in an
invariant against that field's declared attribute, skipping a field name that is ambiguous or
unknown so it cannot manufacture a finding. Measured: 3 — inventory's `category_id`, and 60's
`order_items.product_id` and `products.category_id`, each claiming a uniqueness the model denies.

The two defects recorded below are the ones the rules were built from:

- **inventory:** `data_models.Product.category_id` is `nullable: false` **with** a foreign key;
  the invariant list says *"category_id must be nullable in Product model if not enforced via
  foreign key constraints"*. A direct contradiction between `data_models` and `invariants`.
- **`unique` vs `primary_key`:** `Product.id` is a primary key with `unique: false`, while
  `Category.id` is a primary key with `unique: true`. A primary key is unique by definition, and
  the two entities in the same document disagree.

**Why invisible:** `_check_primary_keys` reads `nullable` and nothing else — `unique` is never
read anywhere in the package. And `invariants` are treated as opaque strings: the only rules are
non-str, duplicate and empty.

---

## 5. `pattern_matches.json` is never read — **CLOSED (both ends)**

**The three `unknown_reference` findings were my rule's error, not a defect.** They flagged
`CUSTOM_DOMAIN_LOGIC`, which
`hierarchical_classifier.classify_requirement_2step` appends to its option list as a deliberate
"matches no standard pattern" answer, and `CUSTOM_OR_STANDARD_CRUD`, which it returns when no
domain fits. Validating against the two catalogue files alone rejected both. `kernel/pattern_catalog.py`
now owns the pattern vocabulary — the catalogues, the domains and the two sentinels — and **both**
the classifier and the checker read it, so they cannot disagree. This is what plan §6.2 asked for
and it removed all three findings.

**Checker rule:** `kernel/consistency/checks_patterns.py`, called from
`check_architecture_layer`, and the document registered in `loader.py` as a core document. It
takes the allowed ids from `kernel.pattern_catalog`, so it never pulls in `llama_cpp`. It reports
an unknown `pattern_id` as `unknown_reference`, a `confidence` outside `[0, 1]` as an error, a
`contract:` source that names no declared method as `unknown_reference`, and a `confidence` below
0.2 as `low_confidence` — a **note**, since the checker cannot tell a low-confidence-but-correct
classification from a wrong one.

**Measured:** 3 `unknown_reference` (now 0) and 5 `low_confidence` (now **1**, since the field
declarations stopped reaching step F and the read shapes were completed; the mid-points of those
changes were 2 and 6, see the last two subsections, and §9.23 moved the last one back by giving
each entry the confidence of the pattern actually recorded rather than of the model's claim).
`CUSTOM_DOMAIN_LOGIC`
appeared in **three** prompts — cli_tool, inventory and expenses — not expenses alone. The floor
is 0.2 and not 0.5 for a stated reason: 0.2 isolates five matches, while 0.5 would report 88 and
drown the real findings; the threshold is named in the message so it can be argued with.

The document — 0 entries (hello), 11 (cli_tool), 15 (gui), 26 (inventory), 34 (library), 37
(expenses), 38 (60) — was produced by step F, written to disk, and read by **nothing** before
this. Confidences run as low as 0.14 (60) and 0.17 (library).

**The note that started this inquiry is a real defect the floor reports and cannot name.** On
expenses, before the rule/schema tag was added:

```
[low_confidence] 'AGGREGATE_BY_FK_AND_DATE' matched
                 'get_expense_by_id: Returns an expense by its ID' at confidence 0.19
```

`get_expense_by_id` reads one row by its primary key; `AGGREGATE_BY_FK_AND_DATE` is a SUM/AVG
over a foreign key and a date range. The match is wrong — and the *reason* is a catalogue gap,
not model noise: the repository catalogue held six patterns then — `AGGREGATE_BY_FK_AND_DATE`,
`AGGREGATE_BY_FK`, `COUNT_ACTIVE_BY_FK`, `FILTER_WITH_PAGINATION`, `EXISTS_BY_UNIQUE_COMPOSITE`
and `THRESHOLD_SCAN` — and **none of them was "read one record by primary key"**. The requirement
had no correct destination, so step F returned the least-bad option, and 0.19 is it saying so.
(The catalogue holds eight repository patterns now, after `READ_ALL` and `FILTER_BY_FIELD` were
added below; with the five service patterns that is thirteen in all, and still none of them
returns one record found by something other than its primary key — which is why `get_wine_by_name`
remains a gap.)

This is why the severity is a note rather than a warning, and the distinction is exact: the
checker can prove the classifier was **unsure**, and cannot prove it was **wrong**. Moving the
floor does not help — lowering it reports more wrong matches, raising it hides them.

The floor is also blunt in a second way, and this was visible in the same file before the tag:
15 of one run's 34 matches took their `text` from a data-model **invariant** and classified a
field definition as a query pattern. `"expense.amount_cents is non-negative integer" →
AGGREGATE_BY_FK_AND_DATE` (0.2918), `"expense.is_recurring is boolean" → AGGREGATE_BY_FK_AND_DATE`
(0.2498) and `"category.id is auto-incremented primary key" → AGGREGATE_BY_FK_AND_DATE` (0.4653)
are the same category error as the reported one, and all three scored **above** the floor, so
none was reported. The note was the visible tip: step F was being asked to classify statements
that are not patterns at all.

Two of the three fixes that follow from this are now done, and one is not:

- **stop feeding data-model invariants to step F as though they were query patterns** — done, by
  tagging each invariant `rule` or `schema` at step C so only the rules are classified (the last
  subsection of §5);
- **re-derive the document** — done as part of that re-run, and `low_confidence` is now 2;
- **add a read-by-primary-key pattern to the repository catalogue** — *not* done, and still the
  single highest-value addition available, since one `READ_ALL`/`READ_BY_PRIMARY_KEY` pair also
  closes 11 of the gaps.

With the declarations no longer reaching it, the `low_confidence` notes fell to two, both
contract methods that are **compound** operations — `borrow_book` checks availability, creates a
loan and decrements copies; `detect_recurring` scans and may create — and for those low
confidence was the honest answer rather than a symptom. (§9.19 then read `low_confidence` **0**,
because the signature check refuses an impossible claim rather than reporting it at low
confidence. §9.23 moved it to **2**, and that is a correction rather than a regression: the
recorded `confidence` now describes the pattern actually recorded, so a corrected entry reports
its own 0.0699 instead of its claim's 0.2619 and crosses the floor it had been hiding behind.)

**Why invisible:** this was RC9, the one phase of the plan that was never implemented.

### What step F actually discards, and why the note hides the real signal

Step F is already asked "does nothing fit?" at both stages — `CUSTOM_OR_NONE` at the domain
stage, `NO_STANDARD_PATTERN_OPTION` appended to every pattern list — but `classification.py`
throws the first answer away:

```python
FALLBACK_PATTERN = "CUSTOM_OR_STANDARD_CRUD"
...
    if pattern_id != FALLBACK_PATTERN:      # the stage-1 answer is deleted here
        matches.append({...})
```

So the amount of classification that never reaches any document is exactly *asked − written*,
which is countable from the existing output without re-running the model:

| prompt | asked | written | discarded | stage-2 sentinel | no answer |
|---|---|---|---|---|---|
| hello | 0 | 0 | 0 | 0 | — |
| cli_tool | 0 | 0 | 0 | 0 | — |
| inventory | 33 | 22 | **11** | 2 | 39% |
| gui | 23 | 14 | **9** | 0 | 39% |
| expenses | 48 | 34 | **14** | 2 | 33% |
| 60 | 36 | 27 | **9** | 0 | 25% |
| library | 51 | 32 | **19** | 2 | 41% |
| **total** | **191** | **129** | **62** | **6** | **36%** |

Every discarded item is ordinary CRUD — `create_expense`, `read_expense_by_id`, `update_expense`,
`delete_expense`, `create_book`, `read_book_by_id`, and the rest. That is the model answering
*correctly*: `CUSTOM_OR_NONE` is documented as "Basic CRUD (create/read/update/delete by id) or
non-standard custom business logic", so it is one bucket holding two opposite answers, and the
filter cannot separate the legitimate one from the gap. It discards both, which is why the
signal is invisible and why the filter was added in the first place — un-filtered, 62 CRUD rows
would drown the document.

The three answers step F can already distinguish, and what each should become:

| answer | today | should be | a gap? |
|---|---|---|---|
| plain create/read/update/delete | discarded | `STANDARD_CRUD`, kept | **no** — expected, needs no pattern |
| fits no domain at all | discarded | `NO_MATCH`, kept | **yes** — a concept the generator lacks |
| domain fits, no pattern inside it | kept as `CUSTOM_DOMAIN_LOGIC` | `NO_PATTERN_IN_DOMAIN`, kept | **yes** — a pattern the catalogue lacks |

Split that way, the two "yes" rows are the coverage report this whole section has been trying to
construct: `NO_MATCH` counts what has no domain, `NO_PATTERN_IN_DOMAIN` counts what has a domain
but no pattern in it — and the *texts* of both say which pattern to add next. The six stage-2 rows
already demonstrate it, because every one is a list operation whose only candidate,
`FILTER_WITH_PAGINATION`, demands pagination:

```
read_all_categories: Reads all categories from the database.     0.4192
read_all_books:      Reads all Book entities from the database.  0.3967
read_all_authors:    Reads all Author entities from the database. 0.2635
```

That is the same shape as `get_expense_by_id` and points at one concrete addition — a
`READ_ALL`/`READ_BY_PRIMARY_KEY` pair — rather than at a threshold change.

### Built, and what it measured — the first of two measurements

The split is implemented — `pattern_catalog.py` (three ids), the classifier, `classification.py`
(which now filters nothing), `checks_patterns.py` (`missing_pattern` notes) and `report.py` — and
the seven prompts re-ran to **`0 error(s), 0 warning(s), 29 note(s)`**, 61 tests green. The last
subsection below takes this to 21 by removing the field declarations from step F's input, so the
figures here are the mid-point of the change, not its end.

| prompt | rows | pattern | `STANDARD_CRUD` | gap |
|---|---|---|---|---|
| inventory | 35 | 16 | 15 | 4 |
| gui | 23 | 13 | 8 | 2 |
| expenses | 48 | 28 | 19 | 1 |
| 60 | 36 | 24 | 9 | 3 |
| library | 51 | 28 | 18 | 5 |
| **total** | **193** | **109** | **69** | **15** |

**Eleven of the fifteen gaps are `read_all_*`** — `read_all_categories`, `read_all_books`,
`read_all_loans` and the rest, at confidences 0.42–0.90. The other **four are field
definitions** (`category.description is optional`, `author.biography must be a string (non-null)`)
and are not catalogue gaps at all — see below. The only list-shaped repository pattern,
`FILTER_WITH_PAGINATION`, **requires pagination**, so "read them all" has nowhere to land: one
added `READ_ALL` pattern closes those eleven. This is the coverage report the section set out to
build, and it is concentrated enough to act on in a single change.

**Eleven is a floor, not the whole count.** Reviewing the run logs showed `read_all` is
sometimes *absorbed* rather than reported — recorded as a real pattern that does not fit, at a
confidence **above** the floor so nothing reports it:

| match | pattern | confidence |
|---|---|---|
| `CategoryRepository.read_all_categories` (expenses) | `FILTER_WITH_PAGINATION` | 0.35 |
| `ExpenseRepository.read_all_expenses` (expenses) | `FILTER_WITH_PAGINATION` | 0.43 |
| `orders.read_all_orders` (60) | `FILTER_WITH_PAGINATION` | 0.53 |
| `ExpenseService.list_expenses` (expenses) | `FILTER_WITH_PAGINATION` | 0.57 |
| `BudgetRepository.read_all_budgets` (expenses) | `FILTER_WITH_PAGINATION` | 0.57 |
| `InventoryService.list_products` (inventory) | `FILTER_WITH_PAGINATION` | 0.64 |

The list-shaped gap is therefore **eleven reported plus six absorbed**, and a
`READ_ALL`/`READ_BY_PRIMARY_KEY` pattern would claim **seventeen**. (This corrects an earlier
figure of four absorbed, which had counted only the matches named `read_all_*` and missed the
two named `list_*`.) The asymmetry across prompts (library 4/4 to the sentinel, expenses 0/3) is
not run-to-run noise: with no pattern of its own, `read_all` splits between the sentinel and the
nearest list-shaped option, and the wording decides which wins.

**It is not a floor problem, and the numbers settle that.** The floor is
`LOW_CONFIDENCE = 0.2` (`checks_patterns.py`), and the six absorbed matches are at 0.35–0.64 —
every one **above** it. Lowering the floor cannot report them at all; raising it high enough to
catch the cheapest costs far more than it finds: a floor of 0.40 flags 10 matches of which 1 is
list-shaped (nine are correct — `AGGREGATE_BY_FK`, `AGGREGATE_BY_FK_AND_DATE`,
`STATE_TRANSITION_GUARD`, `EXISTS_BY_UNIQUE_COMPOSITE`), 0.50 flags 25 including correct
`STANDARD_CRUD`, and 0.60 flags 42. No threshold catches these, because the model is not unsure
— it is confident and wrong, having had no correct option to choose. The fix is a pattern, never
a number. Full account: `FIX_PLAN.md` §9.17.

**Resolved, and the resolution was two changes, not one.** The read shapes were added to the
repository catalogue — `READ_ALL` (a whole-table read with **no** selection argument) and
`FILTER_BY_FIELD` (the records matching a foreign key or status), with exclusion clauses written
into `READ_ALL` and `COUNT_ACTIVE_BY_FK` so each shape has one home. `read_all` is now
**consistent**: 14 of 14 list reads across the seven prompts land on `READ_ALL`, where they
previously split between a gap and `FILTER_WITH_PAGINATION`.

But the deeper defect was in `classification.py`, and the vocabulary alone did not touch it: the
classifier computes a softmax over the options and the step wrote down **the winner only**,
discarding the runner-up. A `0.70` that beat `0.69` and a `0.70` that beat `0.05` produced
identical records, so the checker could never tell a coin-flip from a decision — which is
precisely why the same requirement reported two ways. `pattern_matches.json` now carries
`runner_up_pattern_id` and `margin`, and a **`narrow_margin`** note reports a match decided by
less than 0.15. Across the seven prompts it reports **10 near-ties** and stays silent on the
rest, and the split is the proof: `filter_expenses` was decided by **0.00** and is reported;
every `read_all_*` was decided by **0.40–0.72** and is not.

Adding `READ_ALL` on its own was measured and was **not** a net win — it fixed 15
classifications and broke 10, becoming a catch-all that swallowed `find_active_members` and
`find_overdue_loans`, which had been on `COUNT_ACTIVE_BY_FK` and `THRESHOLD_SCAN`. It was the
second pattern that made the vocabulary coherent. Full account, including the scaling bug the
margin measurement exposed: `FIX_PLAN.md` §9.18.

> An earlier revision of this section said thirteen of fifteen were `read_all_*`. Classifying
> every gap by the text that produced it gives eleven read-alls and four field definitions. The
> miscount is corrected here rather than quietly.

**Eight of the twenty-nine notes are one root cause.** The four field-definition gaps and four of
the six `low_confidence` notes are the same defect from two sides: step F is asked to classify
two kinds of text, and only one is a *pattern* question.

- **contract methods** are operations, so a pattern can be right for them;
- **data-model invariants** include field *declarations* — `member.is_active must be a boolean`,
  `member.membership_date must be a valid date`, `stock_qty must be updated to a non-negative
  integer`, `wine.storage_location_id must reference a valid StorageLocation`,
  `author.biography must be a string`, `category.description is optional` — which are not
  operations, so **no pattern can ever be right**.

Which note appears depends only on where the softmax happened to land: a real pattern gives
`low_confidence` (4), the sentinel gives `missing_pattern` (4). The remaining two
`low_confidence` notes are contract methods that are **compound** operations with no single
pattern — `borrow_book` checks availability, creates a loan and decrements copies in one method;
`detect_recurring` scans and may create. Those are genuinely hard, and low confidence is the
honest answer.

**The fix is a filter, not a threshold:** only invariants stating a rule about *behaviour* belong
on step F — `budget.amount_limit_cents is non-negative` matched `BUDGET_OVERFLOW_GUARD` at 0.66,
a real classification — whereas a declaration of a field's type or nullability does not. That
filter is **now implemented** at step C, where the distinction is made by the grammar rather than
inferred from the prose; the last subsection of §5 measures it.

**The escape-hatch risk was the thing to test, and it does not materialise.** The criterion
was set in advance: a no-answer rate above 50% would mean the option is too cheap. It came back
at 44% — and 69 of those 84 are `STANDARD_CRUD`, a *correct* answer. Every `STANDARD_CRUD` row
was read, and a keyword test for aggregate text run over all 69: **no requirement that has a
pattern absconded into the sentinel.** All 109 genuinely pattern-shaped rows still reached real
patterns. The five rows the keyword test flagged are its own false positives — four matched
*unique* in "by its unique identifier" (a primary-key read) and the fifth is a create whose
description mentions a uniqueness check. So the 50% criterion was measuring total no-answers
when the question is whether the sentinel *swallows* anything; it does not, and 44% is simply
the true proportion of CRUD in these repositories — exactly what the 62 deleted rows were.

**Two things the measurement left open**, each narrowed rather than closed:
- the `READ_ALL` pattern (11 gaps), not added because adding a pattern changes what step F can
  answer and needs its own re-run;
- the `0.2` floor, which is documented as needing re-derivation whenever the option list changes
  and now does — `low_confidence` notes read 6 here, and 2 once the declarations stopped reaching
  the classifier (below), as probability mass shifted twice.

### The third item is closed: field declarations no longer reach step F

The bullet that stood here said field-definition invariants should not be classified as patterns
at all. **They are not any more.** Step C now tags each invariant `rule` or `schema` at the moment
it writes it, with the value closed by the grammar (`grammar_open.invariant_list`), and step F
classifies the `rule`s only — the distinction is made where the grammar can enforce it rather
than guessed from prose by a regular expression (the extractor's document pipeline contains none,
and this would have been the first). The declarations stay in `invariants.json`, because §4's
`inconsistent_invariant` rule compares them against the data model and would have nothing to
check without them.

Measured over the five domain prompts, re-run: **invariants reaching step F fell from 75 to 22
(‑71%)**, and no prompt lost all its rules:

| prompt | invariants | `rule` | `schema` | classified before | after |
|---|---|---|---|---|---|
| inventory | 11 | 1 | 10 | 13 | 1 |
| gui | 16 | 3 | 13 | 9 | 3 |
| expenses | 20 | 4 | 16 | 15 | 4 |
| 60 | 36 | 9 | 27 | 23 | 9 |
| library | 11 | 5 | 6 | 15 | 5 |
| **total** | **94** | **22** | **72** | **75** | **22** |

The seven prompts re-ran to **`0 error(s), 0 warning(s), 21 note(s)`**, from 29: the eight notes
this removes are `low_confidence` 6 → 2 and `missing_pattern` 15 → 11 — the declaration noise,
which §5 above showed was mostly scoring *above* the floor and so was never even reported. The
22 surviving rules are genuinely behavioural: `An order can only be confirmed if its status is
'pending'`, `Expense.is_recurring must be false if expense_date is in the future`,
`Loan.return_date must be null if Loan.status is 'active'`.

**One residual `rule` in 22 is a real mis-tag** — `product.category_id must reference an existing
category`, which is referential and which the prompt lists as `schema` explicitly. It is left in
place rather than chased by another full re-run, and recorded rather than rounded away; the full
account is `FIX_PLAN.md` §9.16.

### The catch-all is now `UNKNOWN`, and the attribution is checked — §9.19

The count above was the symptom. The cause was that a requirement no pattern fits came back as
the *nearest* pattern, and the section's own coverage report could not say so — it reported what
the classifier chose, and the classifier never chooses "none of these".

**Measured, and it changed the design.** Offering the sentinel is not the same as the model using
it: across the 34 expenses methods its probability was **0.000 on 30 of them and never above
0.036**. So a refusal rule that waits for "none of these" to win would refuse nothing. `UNKNOWN`
is therefore decided **outside the model**, from the one piece of evidence that cannot be
misread — the method's own return type — and two things had to be fixed for that to work:

- **The signature was not reaching step F.** It classified `name: description`, so
  `get_monthly_expenses(month) -> List[Expense]` and `get_category_spending(...) -> int` were the
  same text to it, and both became `AGGREGATE_BY_FK_AND_DATE`. The parameters and return type are
  now classified, and that alone moved `filter_expenses` from `AGGREGATE_BY_FK` to
  `FILTER_WITH_PAGINATION`.
- **Every pattern now declares its return shape** (`"returns": ["collection"]` beside it in the
  catalogue). A claim whose shape cannot be the method's return type is impossible, and is
  replaced by the next candidate that returns records; when no candidate can be right, the item
  becomes a gap. The correction is confined to record-returning candidates because the first
  version was not: `export_to_csv(...) -> bool` came out "corrected" to
  `EXISTS_BY_UNIQUE_COMPOSITE` — also boolean, shape-valid, and absurd.

**The coverage report the section set out to build.** Of 140 classified items, 132 now carry a
named pattern, 4 are corrected (every one a read misnamed as an aggregate, every one right), and
**7 are gaps — the same four missing kernel features**, not four thresholds. (This subsection's
first measurement read 5 corrections and 8 gaps; the re-run that closed §9.23 regenerated the
documents and moved both by one, which is a generation difference and not a change of rule — the
seven gap texts are identical in the two runs.)

| missing feature | items |
|---|---|
| read one record by a unique field (a name, or a composite key) | 3 |
| export / side-effect operation | 2 |
| compound service operation returning an entity (check, write, decrement) | 1 |
| composite service operation returning a summary | 1 |

Each is a shape the catalogue genuinely lacks — none of the thirteen patterns returns *one record
found by something other than its primary key*, or writes and returns what it wrote. The checker
reports each one with the claim and the refusal (`claimed 'READ_ALL' … returns collection, but
this method returns entity`), so the note is a specification for the pattern to add.

**Still not checked, stated rather than hidden:** an invariant carries no signature, so a guard
chosen for one is judged by the model alone; and library's `find_active_members() ->
List[Member]` stays on `READ_ALL`, because a collection is exactly what it returns and only the
*method name* says it is a status filter. The shape rule cannot see that, and a name-based rule
is the kind that has already been wrong twice here.

---

## 6. Free-text fields whose *content* is never judged

The grammar constrains these fields' *shape*; the checker never judges whether the content is
sensible.

- **`transform` vs the parameter it maps.** `DECIMAL_TO_CENTS` — a money transform — is applied
  to `stock_qty`, `qty`, `reorder_threshold` (inventory), `available_copies`,
  `new_available_copies`, `available_copies_threshold` (library). `CSV_LIST` is applied to the
  booleans `low_active` and `low_only`. Only the enum and the `lookup_entity` coupling are
  checked.
- **`field_name` → `target_param` is meaningless in expenses.** Seven distinct fields —
  `amount_cents`, `description`, `expense_date`, `category_id`, `payment_method`,
  `is_recurring`, `amount_limit_cents` — are all mapped onto the single parameter `expense` (or
  `budget`). The checker verifies only that `target_param` is *a* parameter of the target method,
  so collapsing every field onto one object passes.
- **`return_type` is never judged.** Comparable operations use `None`, `bool`, `Product`,
  `Category` and `Dict[int, int]` across and within documents with no rule. `add_category` and
  `add_product` both return `None` while `InventoryService.add_product` returns `Product`. The
  final documents carry three bare `dict` returns (expenses' `get_monthly_report`,
  `get_yearly_summary`, `get_category_spending`) and `None` on library's four `delete_*` methods;
  `kernel/extraction/return_types.py` repairs only the `dict[str, object]` spelling, because a
  report aggregate names no single entity to repair it to and `None` on a delete is correct.
- **`invariants` are not rules.** `"low_active must be a boolean (default False)"` restates a
  field definition; `"category_id must be nullable … if not enforced via foreign key
  constraints"` is a conditional hedge, not an invariant. No rule requires an invariant to be a
  statement about a real entity or field.
- **`technology` is never checked for coherence with `type`** — `facade: {type: "cli",
  technology: "flask"}` passes.
- **`status` (`explicit`/`deduced`) is never checked** — inventory marks `reorder_threshold` and
  `low_active` as `deduced` although the requirements name both explicitly.
- **`indexes` in `entity_mappings` are never compared with the entity's fields.** Every observed
  index happens to be a real field, so there is no failing instance — the check does not exist,
  not that it fails.

---

## 7. Entity naming — **withdrawn: this section was wrong**

This section claimed 60 names its entities as table names (`categories`, `products`,
`order_items`) while the other prompts use class names. **It does not.** Reading the document
this section describes: `out/60/data_models.json` holds `Customer, Category, Product, Order,
OrderItem, Invoice` — singular PascalCase, identical in style to the other four domain prompts.
Measured across all five, in no prompt does an entity name equal its own
`entity_mappings[].table`.

The claim was written from an earlier run and repeated here without re-reading the file. It is
left in place as a correction rather than deleted, because the reasoning it produced is still
worth recording — the lesson is that a defect list reconstructed from memory of a previous
batch is not evidence, and this one was caught only because a rule was about to be built on
it. The rule that would have reported it (`plural entity names`) is not written, and the
underlying risk — an entity name that is really a table name, which
`entity_mappings[].table` already carries separately — remains genuinely unmeasured.

---

## 8. Feature coverage is unmeasured, and some requirements have no artefact at all

- **Error types — CLOSED (§9.24).** inventory's requirements name `CategoryNotFoundError` and
  `ProductNotFoundError`, and no document had anywhere to record them. There is now an
  `errors.json` registry; both types are in it, and each contract method that can produce one
  names it in `raises`. What stays open is completeness in the other direction: the checker can
  see a `raises` naming nothing registered (`unknown_reference`) and a registered type nothing
  raises (`unused_error`, a note), but it cannot see a failure the requirements describe that the
  registry never recorded. 60's missing `InvoiceNotFoundError` was found only because a contract
  happened to reference it.
- **CLI surface — CLOSED (§9.24).** `components.facade` recorded only `{type, technology}`, so a
  requirement naming eleven `click` commands left no trace. An `invocation` field now records
  `positional`, `options` and nested `commands`, and `inconsistent_facade` checks the parser
  against it. What remains open is the *backing*: `category update` and `category delete` still
  have no service method behind them (see §3), and nothing compares the recorded surface with the
  requirements' own command list — the faithfulness limit stated below. §9.25 added the checks
  that compare the surface *with itself*: an option repeating a subcommand's name, a positional
  whose type is outside the grammar's set, and a command, subcommand or option listed twice.
  §9.27 closed the first of them in the grammar, so they fire on **none** today (they reported
  six commands before: inventory 1, 60 5). What they still cannot see is a verb recorded as an
  option when *no* subcommand shares the word — expenses' `category -add` with no
  subcommands at all — because `-add` and `-id` are the same kind of thing to a checker with no
  list of verbs, and inventing one would flag every program whose options include a word that is
  also a verb.
- **Nothing measures the ratio in either direction:** how much of the requirements is
  represented, or how much of the output is grounded in them. This is the limit noted in
  `FIX_PLAN.md` §9.9 — the checker verifies internal agreement, never faithfulness — and it is
  the source of every finding in §3, §7 and §8.

---

> **Final tally for §5, after the §9.24 re-run.** The subsections above quote each change's
> mid-point, because that is what each measurement established at the time. On the final
> documents — regenerated once more with the error registry and the CLI surface in place — the
> pattern notes read `narrow_margin` **10** (4 domain, 6 pattern), `missing_pattern` **6**,
> `corrected_claim` **1** and `low_confidence` **0**, and the whole run is `0 error(s), 6
> warning(s), 43 note(s)`. The 6 gaps are the same four missing shapes the subsection above
> names, so nothing in the analysis changed; only the count moved, with the documents.
>
> **The six warnings §9.25 added are gone, closed in the grammar (§9.27).** §9.25's three
> surface checks reported one word used as both an option and a subcommand on six commands; the
> command grammar now admits no shape that can hold both at once, so `invalid_value` fires on
> none of them. The ten warnings on the final documents are different content defects this run
> produced — 3 `contradictory_raise`, 3 `duplicate_error_subject`, 2 `unreachable_error`, 1
> `mismatched_transform`, 1 `missing_command`. Every one of those five classes was reachable
> under the §9.24 rule set as well, and none is a `components` or `service_contracts` output
> §9.27 could cause (it touches only the facade's command grammar): they are the generation
> variance the checker is built to report, recorded rather than chased.

## What is cheap to close — all six closed at both ends

Ranked by (defects caught ÷ effort), all implemented and all removed from the output:

| # | work | rule | when added | now |
|---|---|---|---|---|
| 1 | §1 interface agreement | `inconsistent_interface` | 10 | **0** |
| 2 | §2 parameterless methods | `missing_parameters` | 12 | **0** |
| 3 | §3 crud vs methods | `unmet_crud_operation` | 6 | **0** |
| 4 | §5 pattern_matches | `checks_patterns.py` + `missing_pattern` + `narrow_margin` | 3 + 5 | **0** + 6 gap notes, 10 narrow-margin |
| 5 | §4 `unique` vs `primary_key` | `non_unique_primary_key` | 1 | **0** |
| 6 | §4 invariant vs model | `inconsistent_invariant` | 3 | **0** |
| 7 | §5 catch-all + attribution | `corrected_claim` (§9.19) | — | **1** correction, 6 gaps = 4 missing shapes |

Three of the six were fixed by changing the extraction (the chained step C, the operations block
carried into E and H, the uniqueness rule in step B), two by a rule of mine being wrong (the
pattern sentinels, the confidence severity), and one — the `unique` flag — by a one-line prompt
addition. The full account, including the content-volume table and the one regression the fix
introduced and corrected, is `FIX_PLAN.md` §9.14.

**What the content-volume comparison caught, and why it matters.** A clean checker tally is worth
nothing if the documents emptied, so every document's item count was compared before and after.
That is how two things surfaced that no rule would have reported. First, `cli_tool`'s invariants
went 11 → 0 — and the eleven turned out to be an invented bookshop (`isbn`, `publisher`,
`genre`, `copies_received - copies_ordered`) for a program that reads CSV and prints JSON, so
zero is the correction. Second, repositories began collapsing to exactly the operations step D
listed, because my instruction read as a ceiling rather than a floor; comparing the counts
exposed it, and gui's repositories went 6 → 14 once the wording was fixed.

**One change is genuinely thinner and cannot be judged from here: the adapter lists.** inventory
18 → 11, 60 27 → 13, library 31 → 19. Every adapter that remains resolves to a real service
method — that is what the adapter rules check, and they pass — but nothing measures how many of
the requirements' *actions* an adapter list ought to cover. This is §8's limit exactly.

The remaining sections (§6 transforms, §7 naming, §8 coverage) are not checker work. They need a
reading of the *meaning* rather than agreement about structure — whether `DECIMAL_TO_CENTS`
belongs on a boolean, whether `expenses` collapsing seven fields onto one `expense` object is
sensible, whether the documents cover the requirements at all — and belong with the deferred
repair pass. §8 in particular states the checker's hard limit: it verifies internal agreement,
never faithfulness, so no rule in it can be written without the requirements as input.
---

> **§9.28 — the three content contradictions are now repaired in the pipeline, not just
> reported.** The four warnings above (`contradictory_raise`, `duplicate_error_subject`,
> `unreachable_error`, `mismatched_transform`) and the `missing_command` warning that remains
> were the last findings on the field batch. Three of the four are contradictions *inside one
> document* — two names for one missing record, a create that fails to find what it creates, and
> an adapter field whose transform names a value it does not hold — and a contradiction inside a
> document is decidable by a total function of that document, so it does not need the grammar or
> the prompt. `kernel/extraction/repairs.py` is that function: it collapses the duplicate error
> names to the one a method actually raises (redirecting any reference to the dropped spelling),
> drops a not-found `raise` from a method that creates the very entity it claims not to find, and
> sets a transform to `DIRECT` when the field name describes no such value. It only ever **deletes
> or redirects a value the same document already contradicts** — it never invents one, never
> rewrites a signature, and never touches a document whose values are consistent.
>
> **The final tally, one clean batch on frozen code:** `0 error(s), 1 warning(s), 55 note(s)` over
> all seven prompts. The single warning is library's `missing_command` (the requirements name
> `book search`; the surface lacks it) — that one needs the requirements text and a verb
> vocabulary the checker does not own, and no repair can close it honestly, so it stands. The
> notes are `unused_error` 19, `narrow_margin` 13, `missing_pattern` 10, `corrected_claim` 3,
> `low_confidence` 2, and the rest `empty_section`.
>
> **Content is unchanged where no contradiction existed.** The only document item count that
> moved on any prompt is the error registry (inventory 10 → 8, expenses 10 → 9, both because a
> duplicate name was removed); `intentions`, `invariants`, `data_models`, `service_contracts`
> methods, `interaction_adapters` and `pattern_matches` are identical on all seven. Suite 256
> tests, `py_compile` clean. Full account: `FIX_PLAN.md` §9.28.
>
> **The residual generics in §6 stand and are deliberate.** expenses' three bare `dict` report
> returns and library's four `None` deletes are unchanged by the repair pass, because
> `return_types.GENERIC_RETURNS` targets only the `dict[str, object]` spelling: a report
> aggregate names no single entity to repair it to, and `None` on a delete is correct Python.
