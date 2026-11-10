# Direct GPT-6 Luna acceptance suites

These are independent behavioural checks for the seven outputs under
`out/chatgpt_compare/`.  They are deliberately separate from the subagents'
own smoke tests and follow the same idea as `tests/e2e_*_acceptance.py`: use a
fresh SQLite database, drive the public CLI/service surface, and report one
line per check.

The suites do not modify the generated projects.

## Run everything

Use the interpreter required by the prompt (Python 3.12):

```sh
python3.12 tests/chatgpt_acceptance/run_all.py
```

To exercise behavior that currently fails to import on 3.12, run the same
suites with 3.14:

```sh
python3.14 tests/chatgpt_acceptance/run_all.py
```

The known differences are recorded by:

```sh
python3.12 tests/chatgpt_acceptance/compat.py
```

`compat.py` imports each package with Python 3.12 and writes
`out/chatgpt_compare/chatgpt_python312_compat.json`.

## Run one suite

```sh
python3.12 tests/chatgpt_acceptance/hello.py out/chatgpt_compare/hello_world
python3.12 tests/chatgpt_acceptance/cli_tool.py out/chatgpt_compare/cli_tool
python3.12 tests/chatgpt_acceptance/inventory.py out/chatgpt_compare/inventory
python3.12 tests/chatgpt_acceptance/gui.py out/chatgpt_compare/gui
python3.12 tests/chatgpt_acceptance/business.py out/chatgpt_compare/60
python3.14 tests/chatgpt_acceptance/expenses.py out/chatgpt_compare/expenses
python3.14 tests/chatgpt_acceptance/library.py out/chatgpt_compare/library
```

Each suite writes `out/chatgpt_compare/<project>/chatgpt_<suite>_results.json`.

## Current expected findings

- Hello, CSV, inventory and `60` are expected to pass their checks and run on
  Python 3.12.
- The GUI's domain checks pass, but the real one-frame check fails in the
  current environment with `OpenGL.error.GLError` inside `GlfwRenderer`.
- Expenses and library pass their behaviour suites on Python 3.14, but fail
  import on Python 3.12 because class-scope `list` methods shadow the builtin
  during annotation evaluation.  `compat.py` records that directly.

These suites cover the explicit prompt requirements and the important edge
cases; they are not a production certification.
