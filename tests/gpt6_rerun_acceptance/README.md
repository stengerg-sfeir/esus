# GPT-6 Luna rerun acceptance suites

These suites target the outputs generated on 2026-11-13 under
`out/gpt6_rerun/`.  The 2026-11-10 suites in `tests/chatgpt_acceptance/` are
kept as historical fixtures: they import package layouts and service APIs from
that earlier run, which the rerun did not reproduce.

Run all suites with the interpreter required by the prompts:

```sh
python3.12 tests/gpt6_rerun_acceptance/run_all.py out/gpt6_rerun
```

Run one suite:

```sh
python3.12 tests/gpt6_rerun_acceptance/inventory.py out/gpt6_rerun/inventory
```

The suites use fresh SQLite databases and drive the public service or CLI
surface.  They are independent of each generated project's own tests.

The `expenses` suite uses `out/gpt6_rerun/expenses`, the run whose wall time is
reported in the benchmark.  The clean `out/gpt6_rerun/expenses_retry` output is
not timed and is not part of this suite.

## Coverage

| Suite | Checks | Notes |
| --- | ---: | --- |
| hello | 4 | entry point, output, annotation, clean exit |
| cli_tool | 10 | dynamic headers, output file, CSV quoting, errors |
| inventory | 13 | models, schema, CRUD, reports, Click CLI |
| gui | 9 | domain rules, persistence, tkinter wiring |
| expenses | 11 | schema, CRUD, budgets, reports, CSV, recurring, Click CLI |
| library | 12 | schema, CRUD, borrowing, overdue, search, cascades, CLI |
| `60` | 14 | schema, catalog, order state machine, invoices, searches, CLI |

The GUI suite cannot launch a real window here because the installed Python
3.12 lacks `_tkinter`; its GUI check is static.  This is recorded as a
limitation, not counted as a passed runtime check.
