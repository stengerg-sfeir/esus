# Generic runtime acceptance harness

`worker.py` runs one generated prompt in a fresh interpreter. It reads the
extracted documents, imports the generated package, creates a temporary
SQLite database, and checks:

- package import and `cli.py --help`;
- every method contract with a scalar binding and effect:
  - a valid fixture reaches the declared effect;
  - an invalid fixture raises the declared error;
- CLI leaf `--help`;
- schema metadata (keys, nullability, uniqueness, foreign keys, autoincrement);
- repository read/update/delete round-trips and unique/FK constraints where the
  generated shape exposes a usable create/read pair;
- optional `scenarios.json` scenarios.

The outer runner is:

```sh
python3 scripts/run_bench_acceptance.py out/validation/bench
```

It writes one JSON report per prompt under
`out/validation/bench/acceptance/` and a `summary.json`.

## Scenario format

Scenarios are data, not test code. They may be generated from the
requirements and reviewed before execution.

```json
{
  "scenarios": [
    {
      "name": "confirm reserves stock",
      "setup": [
        {"entity": "Order", "as": "order",
         "values": {"status": "pending"}}
      ],
      "when": {
        "service": "OrderService",
        "method": "confirm_order",
        "args": [{"ref": "order.id"}]
      },
      "expect": {
        "fields": {"order.status": "confirmed"},
        "rows": {"Invoice": 1}
      }
    }
  ]
}
```

`setup` inserts a model row through the generated store, replacing any
supplied fields and filling the remaining non-key fields with type-appropriate
fixtures. `as` exposes the row and its primary key as `alias.id` and
`alias.<primary_key>`. `when` calls one generated service or repository method;
`args` may be a positional list or a keyword mapping. `expect.fields` reads the
row back after the call; `expect.rows` counts an entity. `expect.error` names
the expected exception class.

The harness never edits generated modules. Prompt-specific semantic gaps are
reported as scenario failures so they can be fixed in extraction, review or
the generator and then regenerated.
