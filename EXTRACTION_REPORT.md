# Architecture extraction — regeneration and consistency report

**Date:** 2026-09-29 / 2026-09-30
**Model:** `../models/Ministral-3-3B-Instruct-2512-Q4_K_M.gguf` (GGUF, Q4_K_M)
**Runtime:** CPU only, `n_ctx=8192`, `n_threads=8`, `flash_attn=False`, `logits_all=True`
**Script:** `extract_archi.py` (8 steps per prompt: A intentions, B data models, C invariants, D components, E service contracts, F pattern classification, G interaction adapters, H persistence ports)
**Checker:** `check_consistency.py` (reworked; see [Tooling](#tooling))

---

## 1. What was run

All seven requirements prompts were regenerated from scratch with `extract_archi.py`, then every
output directory was checked for internal consistency.

| prompt | source | wall clock |
|---|---|---|
| hello | `prompts/prompt_hello_world.txt` | 112 s |
| cli_tool | `prompts/prompt_cli_tool.txt` | 273 s |
| inventory | `prompts/prompt_inventory.txt` | 982 s |
| gui | `prompts/prompt_gui.txt` | 1 213 s |
| expenses | `prompts/prompt_expenses.txt` | 1 366 s |
| 60 | `prompts/prompt_60.txt` | 1 589 s |
| library | `prompts/prompt_library_system.txt` | 2 444 s |
| **total** | | **~2 h 13 m** |

Outputs are in `out/<name>/`: `intentions.json`, `data_models.json`, `invariants.json`,
`components.json`, `service_contracts.json`, `interaction_adapters.json`,
`persistence_ports.json`, `pattern_matches.json`, `run.log`.

---

## 2. Consistency verdict

**7 errors, 52 warnings across 7 prompts.** No prompt is fully clean except that the two
no-persistence prompts (hello, cli_tool) produced no *errors*.

| prompt | errors | warnings |
|---|---|---|
| hello | 0 | 3 |
| cli_tool | 0 | 4 |
| inventory | 0 | 5 |
| gui | **3** | 12 |
| expenses | **2** | 5 |
| 60 | **1** | 6 |
| library | **1** | 17 |

### Findings by rule

| count | severity | rule | meaning |
|---|---|---|---|
| 23 | warning | `unknown_reference` | a name points at something that does not exist |
| 9 | warning | `inconsistent_adapter` | adapter transform and lookup entity disagree |
| 8 | warning | `no_repository` | CRUD entity has no repository |
| 6 | warning | `unresolved_adapter_target` | adapter target services cannot be resolved |
| 3 | **error** | `primary_key_mismatch` | mapping primary key is not a field of the entity |
| 2 | warning | `placeholder_value` | placeholder left by the extractor |
| 1 | **error** | `class_name_entity` | entity field holds a class name |
| 1 | **error** | `duplicate_entry` | duplicate entry |
| 1 | **error** | `malformed_document` | document is not valid JSON |
| 1 | **error** | `no_mapping` | repository entity has no entity mapping |
| 4 | warning | (one-offs) | `empty_section`, `invalid_value`, `missing_primary_key`, +1 |

---

## 3. Systemic failure modes

### 3.1 Step E and step G name services differently — affects every prompt

Steps E (service contracts) and G (interaction adapters) independently invent service names, and
they almost never agree. Of ~50 adapters produced across all prompts, **only 3 resolve**.

| prompt | adapters | unresolved | what the two steps produced |
|---|---|---|---|
| hello | 1 | 1 | adapter → `cli`; no contract declares it |
| cli_tool | 3 | 3 | `error_handler`, `file_reader`, `file_writer` vs `CSVToJSONConverter` |
| inventory | 11 | 8 | `InventoryService`, `InventorySystem` vs `InventoryManagementSystem` |
| gui | 9 | 9 | `wine_service`, `storage_service` vs `WineShopInventoryManager` |
| expenses | 14 | 14 | `BudgetService`, `CategoryService`, `ExpenseService` vs `ExpenseTrackingSystem` |
| 60 | 12 | 12 | `CustomerService`… vs **"Customer Management Service"** |
| library | — | 0 | targets resolve; 17 method/param names do not |

`60` shows the mechanism most clearly: step E emitted human-readable service names containing
spaces (`"Customer Management Service"`, `"Invoice Management Service"`, …) while step G emitted
identifier-style names (`CustomerService`, `InvoiceService`, …). Normalisation cannot bridge those.

**Consequence:** the adapter layer, which is what maps user input onto domain calls, is unusable
as generated for six of the seven prompts.

### 3.2 Step H invents persistence that `data_models` does not contain

- `Expense` invented as a repository entity for **hello** and **cli_tool** — prompts with no domain model at all.
- `WineLocationMapping` invented for gui.
- `ExpenseRepository` used as an *entity name* for expenses (a class name, not an entity → also
  has no mapping).
- gui emits **two** repositories for `Wine` (`WineRepository` declared twice).

The mirror image is `no_repository` (8 findings): CRUD entities declared for budget/category/
expense/product/invoice/order with no repository behind them — inventory `Product`, expenses
`Budget`/`Category`/`Expense`, 60 `Category`/`Invoice`/`Order`/`Product`.

### 3.3 Primary keys disagree between step B and step H

Hard errors, three of them:

- gui: `Wine` mapped on `wine_id`, `StorageLocation` on `location_id` — `data_models` declares `id` for both.
- 60: `Customer` mapped on `customer_id` — `data_models` declares `id`.

### 3.4 Adapter transforms are mislabelled

9 findings of the form *"sets `lookup_entity` X but its transform is `DIRECT`"* (gui 7, inventory 1,
expenses 1). Per the step-G contract those should be `LOOKUP_ID`. One further case sets
`lookup_entity: "null"` (the string) with transform `ISO_DATE`.

### 3.5 Placeholders still leak

2 findings of `{"name": "none", "type": "None"}` in repository `find_all` methods (gui).

---

## 4. Task truncation — `max_tokens=4096`

`library`'s components step generated **4 097 tokens** — exactly the hard `max_tokens=4096`
ceiling — and the resulting `components.json` is cut off mid-document:

```
19841 bytes;  parse error at char 19841 (the final byte)
MALFORMED: components.json: Expecting ',' delimiter (line 34, column 18982)
```

The content after that point is **lost, not merely unparseable**: `library`'s `crud_services`
list is incomplete, so the checker cannot even report on it.

This is also the case that proves the value of the checker rework: on this exact real file the
previous checker died with an uncaught `json.decoder.JSONDecodeError` and produced **no report at
all**, while the current one names the file and position and still delivers the other 17 findings.

The same ceiling is close for other prompts: `service_contracts` reached 3 274 tokens (library),
`interaction_adapters` 2 102 tokens, `data_models` 2 064 tokens.

---

## 5. Performance observations

### 5.1 Step F dominates run time and produces no output

Step F (pattern classification) does two forward passes per item — domain, then pattern — and
calls `llm.reset()` before each one, so **every classification re-prefills its prompt from
scratch**. It prints nothing per item, so it looks like a hang in the log.

- library: 47 methods → ~94 re-prefills → ~15 min of silent CPU
- 60: 26 methods → ~52 re-prefills → ~15 min

With `logits_all=True` (required for the classifier's `logprobs`, and needed by no other step) the
prompt prefill also recomputes vocabulary logits for every token, which is why each pass is
expensive on CPU.

### 5.2 Memory is not a constraint

Measured during a large run: 62 GB total, 52 GB available, **no swap**; the extraction process sat
at 7.5 GB RSS and ~660 % CPU. The `logits_all` scores buffer is real but comfortable here, so
memory pressure is ruled out as a cause of any earlier truncated log.

---

## 6. Tooling

### 6.1 `check_consistency.py` rework

The checker was reworked into `kernel/consistency/` (loader, naming, report, methods, one module
per document, two orchestrators) with `check_consistency.py` as a 61-line CLI. Behaviour changes:

| before | after |
|---|---|
| crashed with a traceback on any malformed file | reports file, line and column, then continues |
| empty `invariants` was an ERROR | it is a warning (step C forbids inventing rules, so empty is often correct) |
| absent `interaction_adapters`/`persistence_ports` was an ERROR | not a defect (`--no-persistence` runs lack them) — except when `components.persistence.required` is true |
| adapter mismatches reported one line per adapter | collapsed into one actionable finding when systemic |
| no check on primary keys, FK target fields, adapter methods/params | all added, with spelling-variant resolution and "did you mean" hints |
| `--dirs` only | plus `--all-findings` |

The same CLI contract and exit code are preserved (0 = no errors). The original is kept at
`backup/check_consistency.py.pre_strengthen.bak`.

### 6.2 Open integration gaps

1. **Output filename mismatch.** `extract_archi.py --output PREFIX` writes `PREFIX_intentions.json`,
   while the checker reads `out/<name>/intentions.json`. Runs in this report bridged it with a
   rename step; one of the two should change.
2. **`pattern_matches.json` is never validated.** Step F's output is produced for all seven
   prompts and checked by nothing — an empty or nonsensical classification passes silently.

---

## 7. What the checker cannot tell you

It is an internal-consistency gate, not a correctness test. Specifically it cannot detect:

- whether an entity, service or field that *should* exist is missing (it never reads the prompt);
- whether every intention or invariant is actually served by a contract method;
- whether a transform is semantically right, only whether it resolves;
- whether a parameter type agrees with the field it names.

Closing those requires a ground-truth expectation per prompt, coverage checks and
type-level checks — none of which are in place yet.

---

## 8. Reproduce

```bash
MODEL=../models/Ministral-3-3B-Instruct-2512-Q4_K_M.gguf

# one prompt (reads the requirements on stdin, writes PREFIX_<step>.json)
mkdir -p out/hello
python extract_archi.py --model "$MODEL" --output out/hello/raw < prompts/prompt_hello_world.txt

# rename to the layout the checker expects
for k in intentions invariants data_models components service_contracts \
         interaction_adapters persistence_ports pattern_matches; do
  [ -f "out/hello/raw_$k.json" ] && mv "out/hello/raw_$k.json" "out/hello/$k.json"
done

# check all seven
python check_consistency.py --dirs \
  "hello:out/hello" "cli_tool:out/cli_tool" "inventory:out/inventory" \
  "gui:out/gui" "expenses:out/expenses" "60:out/60" "library:out/library" \
  --all-findings
```

Exit code is 1 when any error is found. Warning-only directories still exit 0.
