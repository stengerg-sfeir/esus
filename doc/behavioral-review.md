# Behavioral review of generated programs

Reviewed outputs:

- `out/hello_same_conditions/generated`
- `out/cli_tool_same_conditions/generated`
- `out/inventory_same_conditions_final/generated`
- `out/gui_same_conditions_final/generated`
- `out/library_same_conditions_final/generated`
- `out/expenses_ngram_mod/generated`
- `out/60_program_clean/generated`

Method: inspect every provisional body against its prompt, contract and model;
run targeted in-process probes against temporary SQLite databases; compare the
acceptance checks with the prompt surface.  This is a review, not a proof: the
probes cover reported branches, not every possible input.

## Verdict

The mechanical CRUD and the tested acceptance paths work.  **The generated
programs are not fully prompt-compliant.**  Several provisional bodies have
concrete behavioral defects outside their acceptance coverage, and the GUI
program does not persist data or run a usable GUI.

## Findings

### Hello world

Verified runnable; prints `Hello, World!`, has `main()`, type hints and the
`__main__` guard.  No provisional body.

### CSV-to-JSON

The tested path works: dynamic headers, stdout, optional output file, missing
input and malformed input all return as expected.  The missing-file path raises
an uncaught `MissingFileError` traceback rather than presenting a clean CLI
error; the prompt asks for clean error handling.  Functionally usable for the
tested cases, not fully polished.

### Inventory

Acceptance: 7/7.  Likely defects:

- `ProductRepository.find_low_stock_products()` crashes with
  `AttributeError: 'dict' object has no attribute 'reorder_threshold'` because
  it treats a store dictionary as a model.
- `InventoryService.list_products(None, False)` filters to low stock instead
  of returning all products; only `None` and `True` are acceptance-tested.
- `InventoryService.update_product(id)` crashes with `AttributeError` when
  `data` is None; `product update --id` is not acceptance-tested.
- `InventoryService.restock` accepts a negative quantity and can persist
  negative stock; the extracted invariant requires stock to remain non-negative.
- `ProductRepository.aggregate_stock_value_by_category()` omits categories
  with no products, while `InventoryService.stock_value_by_category()` includes
  them as zero.  The two public results disagree.
- `add_product` with omitted fields can reach a raw SQLite `NOT NULL` error
  because the service signature makes every argument optional.

### GUI

Acceptance: 8/8, but the GUI itself is only statically inspected.  Major
defects:

- `gui.build_gui()` constructs `Store()` without a database path or `SCHEMA`;
  the running GUI is in-memory and does not persist across restarts, contrary
  to the prompt.  It also permits a wine without a storage location and keys
  repositories by entity name, so the declared service wiring would not find
  `WineRepository`/`StorageLocationRepository`.
- `cli.py` has empty `BINDINGS` and no subcommands, so its CLI cannot run any
  command.
- `WineInventoryService.cancel_order` decrements stock instead of releasing
  the reserved quantity; a confirm/cancel round-trip corrupts inventory.
- `WineInventoryService.search_wines_by_name` delegates to exact equality and
  returns nothing for a partial name, despite promising a name search.
- `WineInventoryService.check_storage_location_capacity` returns `True` for
  every persisted wine because the storage location is non-null; the actual
  capacity branch is unreachable and compares wine rows, not bottles.
- `WineInventoryService.validate_wine_pricing` returns `True` when only one of
  cost/selling price is supplied, so partial updates bypass the price rule.
- `WineInventoryService.get_storage_location_summary` counts wine rows, not
  bottles, and reports utilization as a fraction rather than a percentage.
- `StorageLocationRepository.update` allows shrinking capacity below the
  number of bottles already assigned.
- `assign_wine_to_location(None)` returns `True` without moving the wine;
  a missing location can leak a raw `KeyError`.
- `export_inventory_to_csv` leaks raw filesystem errors and writes to the
  current directory for an empty path.

### Library

Acceptance: 17/17.  Edge defects:

- `LibraryService.return_book` only checks `return_date`, not `status`; a loan
  with `status='returned'` and a null return date is returned again and its
  copy count is incremented.
- `get_overdue_loans` excludes `status='returned'` even when `return_date` is
  null, while the stated rule is `due_date < today and return_date is None`.
  The status/return-date combination is inconsistent, but the edge is untested.
- `LibraryService.search_books` is not used by the CLI; the CLI binds directly
  to the repository search.  The service method works, but the declared service
  layer is bypassed.
- Borrow/return/search/renew paths covered by acceptance work, including
  transactions and duplicate-return protection for normal returned records.

### Expenses

Acceptance: 13/13.  Defects:

- `ExpenseRepository.get_top_spending_categories` filters a date range with
  `startswith(start)` and `endswith(end)`, so a normal range with distinct
  start and end dates returns no expenses.
- `ExpenseService.get_monthly_report` compares each individual expense to the
  budget instead of the month's total.  A month with two 600-cent expenses and
  a 1000-cent limit reports `on_track` instead of `exceeded`.
- `ExpenseService.get_yearly_summary` uses `(category, month)` as the top
  category key, returning duplicate category entries rather than one yearly
  total per category.
- `detect_recurring` updates the database but returns the pre-update model
  objects, whose `is_recurring` field is still false; callers relying on the
  returned records see stale values.
- `export_to_csv` leaks raw filesystem errors for missing directories.

### 60

Acceptance: 9/9.  Core order lifecycle and persistence pass.  Remaining
defects:

- `CustomerRepository.find_invoices_by_customer_id` treats an order id as an
  invoice id (`self._store.get('Invoice', 'invoice_id', order_id)`); it can
  return another order's invoice when ids diverge.  The customer invoice
  service path works; this repository convenience method is wrong.
- `ReportService.get_order_status_report` only includes statuses that occur;
  it omits zero-count statuses such as `pending` when no pending order exists.
- CSV export methods leak raw filesystem errors and do not create parent
  directories.
- `read_customer_by_id` raises `CustomerNotFoundError` while its annotation
  also permits `None`; the contract is ambiguous, and the dead `None` branch
  is unreachable.
- Category/product/user extras are largely verified by the acceptance suite;
  category deletion, some finder combinations and all exports remain untested.

## Acceptance coverage gaps

- GUI: only static structure; no event loop, no GUI CRUD, no persistence.
- Inventory: negative restock/update, `list_products(..., False)`, direct
  low-stock repository use, empty-category aggregates, missing-field service
  calls and category update/delete are untested.
- GUI: search, summary, capacity-check method, pricing partials, order
  confirm/cancel, update/delete edge cases, export paths and all CLI commands.
- Expenses: top-category date ranges, monthly budget status with multiple
  expenses, yearly category aggregation, stale returned records and export
  error paths.
- 60: report zero-statuses, customer invoice repository path, exports,
  category delete/read and several finder combinations.
- Library: status-only returned loans, overdue with null return date, inactive
  borrower policy and the service-level search path.

## Conclusion

Do not describe the generated code as fully compliant or fully verified.  The
acceptance tests establish that the covered scenarios run.  The defects above
show that the provisional bodies and the GUI do not yet satisfy all explicit
prompt requirements.  They should be fixed or covered by new behavioral tests
before claiming production readiness.
