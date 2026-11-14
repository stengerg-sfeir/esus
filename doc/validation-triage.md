# Validation triage: non-generatable prompts

First pass over the 10 `not_generatable` prompts from the 2026-11-13 full
run (`kaggle-20261113-121941`). The full run produced 28 `direct`,
22 `review` and 10 `not_generatable` results. `direct` is renamed
`successful` in the next runner version.

The raw outputs are in the Kaggle run directory
`out/validation/runs/kaggle-20261113-121941/<prompt>/`.

## Summary

| Prompt | Domain | Hard blocker(s) | Root cause | Fix class |
| --- | --- | --- | --- | --- |
| `prompt_03` | in-memory todo | persistence `required=true` with `technology=none` | contradiction: the prompt says *in memory*, so persistence is not required | generic persistence normalization |
| `prompt_13` | inventory | `Product search` has no method behind it | missing `sku` field and missing search service/repository method | model + capability extraction |
| `prompt_18` | contacts | `Contact export` has no method behind it | missing import/export services; the surface also lacks `import` | capability extraction |
| `prompt_19` | tasks | `Task export` has no method behind it | missing import/export services; the surface also lacks `import` | capability extraction |
| `prompt_26` | library loans | `LoanRepository.get_active_loans_for_member` filters `Member ID`, but `Loan` has no `member_id` FK | model fields are named `book_primary_key` / `member_primary_key`; the service also contains order-shaped `confirm_order`/`cancel_order` methods | model/FK + service repair |
| `prompt_32` | order state machine | `OrderStateException` is raised but not registered | invented/unregistered error class | error registry/contract repair |
| `prompt_34` | order + lines | adapter maps `order_data` fields with a `BOOL_TO_ONE` transform for `is_valid` | nested order-lines structure collapsed into one scalar parameter | adapter/nested-capability repair |
| `prompt_40` | order + notification | persistence required but `data_models` and `crud_services` are empty, so `persistence_ports.json` is missing | extraction produced no domain entities | data-model extraction |
| `prompt_41` | library | boolean fields use `ENUM_LOOKUP` in the adapter | transform inference confused bool fields with lookup fields | generic adapter transform repair |
| `prompt_60` | business orders | `CategoryService.create_category` raises `InvalidCategoryNameError`, not registered | invented error; also 1 open contract and 1 tie | error registry/contract repair |

## Details

### `prompt_03` — persistence contradiction

```text
components.persistence: required=true but technology='none'
```

The model is a `Task`, with CRUD services, but the prompt explicitly says
“store the tasks in memory”. `technology=none` is therefore correct;
`required=true` is not. This is a deterministic normalization candidate:
when persistence technology is `none`, either mark persistence not required
or use a memory-specific technology. No LLM call should be needed.

### `prompt_13` — missing SKU and search

The extracted `Product` model is:

```text
id, name, category, price, stock_quantity
```

It has no `sku`, although the prompt requires unique SKUs. The CLI has
`Product search`, but no service method backs it. This is not a review tie:
the extraction did not create the required model field or search capability.

### `prompt_18` and `prompt_19` — import/export capability missing

The prompts require CSV/JSON import and export. The extracted services contain
only CRUD methods. The surface has an `export` command, but no method backs it;
`import` is not extracted at all.

Both are missing-capability problems. Adding an adapter alone would produce a
dead command; the service/repository operations must exist first.

### `prompt_26` — wrong FK names and order-shaped service methods

The `Loan` model has:

```text
book_primary_key   -> Book.id
member_primary_key -> Member.id
```

The repository filter expects a `Member ID` relation, but `Loan` does not
declare `member_id`. The service also contains `confirm_order` and
`cancel_order`, which belong to the order domain, not the library domain.

This needs a model/relationship repair followed by a service repair; it is not
safely fixable by accepting the review question.

### `prompt_32` — unregistered state error

`OrderService.confirm_order`, `ship_order` and `cancel_order` raise
`OrderStateException`. The error registry does not contain that class. Either
register the error or replace those raises with a registered error. The prompt
requires explicit transitions, so the transition checks should remain.

### `prompt_34` — nested order lines collapsed into a scalar

The adapter for `create_order_with_lines` maps every input field to the same
parameter, `order_data`, and maps `is_valid` with `BOOL_TO_ONE` to
`ordercreationdata`. That signature cannot represent multiple order lines.

This is a nested-capability problem: the service needs a line collection
(or a dedicated create-command path), and the adapter must serialize the
collection, not reuse one scalar parameter.

### `prompt_40` — empty domain model

The extraction produced:

```text
data_models: []
crud_services: []
```

while `components.persistence.required=true` and technology is SQLite. There
is no `persistence_ports.json`. The prompt clearly needs orders and a
notification abstraction, so this is a missing-domain model failure, not a
flag-only problem.

### `prompt_41` — boolean fields mapped as enums

`availability_status` and `membership_status` are booleans, but the adapters
use `ENUM_LOOKUP`. The correct transform is boolean-direct (or the existing
boolean transform), not enum lookup. This is a generic adapter-repair rule:
transform must agree with the target field type.

Two method contracts are also open, but they are secondary to the mismatch.

### `prompt_60` — unregistered category error

`CategoryService.create_category` raises `InvalidCategoryNameError`, which is
not in `errors.json`. The prompt does not require category-name validation, so
the safest repair is to remove that raise rather than register a new error.
The open method contract and tie should be handled after the hard blocker is
gone.

## Priority

1. **Generic fixes**
   - persistence consistency (`prompt_03`);
   - adapter transform/type agreement (`prompt_34`, `prompt_41`);
   - unregistered error detection/repair (`prompt_32`, `prompt_60`);
   - missing model fields/relationships (`prompt_13`, `prompt_26`).
2. **Capability extraction**
   - import/export methods (`prompt_18`, `prompt_19`);
   - nested order-lines representations (`prompt_34`);
   - missing domain models (`prompt_40`).
3. **Review-only leftovers**
   - open ties and method contracts after the hard blockers are removed.

Only the affected prompts should be regenerated after each fix; rerunning all
60 prompts is unnecessary until the structural rules are corrected.

## Resolution (2026-11-14)

The generic repair pass and the second full run (`kaggle-20261113-170925`,
**32 successful / 27 review / 1 hard**) cleared the structural blockers. The
last hard case was a new `null` persistence document on `prompt_03`; the skip
path now omits the file and only unifies ports when an object exists, so the
archived output re-probes as review.

| Prompt | After | Evidence |
| --- | --- | --- |
| `prompt_03` | review | in-memory persistence normalized; no null ports |
| `prompt_13` | successful | search capability method added |
| `prompt_18` | successful | CSV export service + prose import leaf |
| `prompt_19` | review | JSON export + import; open ties only |
| `prompt_26` | review | FK names and create fields repaired |
| `prompt_32` | successful | errors registered; void mapping target fixed |
| `prompt_34` | review | adapter mismatch gone; open tie |
| `prompt_40` | successful | `Order` inferred from prose, CRUD/persistence enabled |
| `prompt_41` | successful | bool transforms corrected |
| `prompt_60` | review | validation raise dropped; open contract only |

The adjusted full-run classification is **32 successful / 28 review / 0 not
generatable** after the `prompt_03` skip-path fix. Remaining work is review
quality, not structural generation.
