"""Behavior acceptance for the CSV-to-JSON CLI prompt.

The prompt is architecture-free (no models, services or command groups), so
the generated program may be the direct `generated/app.py` fallback.  The CLI
spelling of the optional output path is not specified beyond "an optional
output file path"; the test accepts the two common spellings (second positional
path or --output) rather than inventing a required option.

Run after extraction and generation::

    python3.12 tests/e2e_cli_tool_acceptance.py out/cli_tool_same_conditions
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def fail(message):
    raise AssertionError(message)


def entrypoint(out_dir):
    generated = Path(out_dir) / "generated"
    for name in ("app.py", "main.py", "cli.py", "__main__.py"):
        path = generated / name
        if path.is_file():
            return path
    fail(f"no generated entry point under {generated}")


def run(script, *args):
    return subprocess.run(
        [sys.executable, str(script), *map(str, args)],
        cwd=str(script.parent), check=False, capture_output=True, text=True)


def parsed(stdout):
    try:
        value = json.loads(stdout)
    except ValueError as error:
        fail(f"stdout is not JSON ({error}): {stdout!r}")
    if not isinstance(value, list) or not all(isinstance(row, dict)
                                               for row in value):
        fail(f"expected a JSON list of objects, got {value!r}")
    return value


def write_output(script, source, target):
    """Exercise the optional output path in either spelling the model chose."""
    attempts = (
        (str(source), str(target)),
        (str(source), "--output", str(target)),
        ("--input", str(source), "--output", str(target)),
    )
    last = None
    for args in attempts:
        result = run(script, *args)
        last = result
        if result.returncode == 0 and target.is_file():
            return result
    fail("the optional output path did not write a file; last result: "
         f"{last.returncode if last else None} "
         f"{(last.stdout + last.stderr) if last else ''!r}")


def main(argv):
    if len(argv) != 2:
        print("usage: e2e_cli_tool_acceptance.py OUT_DIR", file=sys.stderr)
        return 2
    out_dir = Path(argv[1]).resolve()
    script = entrypoint(out_dir)

    tmp = Path(tempfile.mkdtemp(prefix="csv-json-", dir=out_dir))
    source = tmp / "people.csv"
    source.write_text(
        "full name,age,city\nAda Lovelace,36,London\nGrace Hopper,85,New York\n",
        encoding="utf-8")

    result = run(script, source)
    if result.returncode != 0:
        fail(f"CSV read failed: {result.stdout + result.stderr!r}")
    rows = parsed(result.stdout)
    expected = [
        {"full name": "Ada Lovelace", "age": "36", "city": "London"},
        {"full name": "Grace Hopper", "age": "85", "city": "New York"},
    ]
    if rows != expected:
        fail(f"headers were not used dynamically: {rows!r}")

    target = tmp / "people.json"
    result = write_output(script, source, target)
    if result.stdout.strip():
        fail(f"writing a file should not also print JSON: {result.stdout!r}")
    try:
        written = json.loads(target.read_text(encoding="utf-8"))
    except ValueError as error:
        fail(f"output file is not JSON ({error})")
    if written != expected:
        fail(f"output file differs from stdout behavior: {written!r}")

    missing = run(script, tmp / "absent.csv")
    if missing.returncode == 0:
        fail("a missing input file returned success")
    if not (missing.stdout + missing.stderr).strip():
        fail("a missing input file produced no error message")

    malformed = tmp / "malformed.csv"
    malformed.write_bytes(b"\xff\xfe\x00\x01not text")
    bad = run(script, malformed)
    if bad.returncode == 0:
        fail("malformed CSV returned success")
    if not (bad.stdout + bad.stderr).strip():
        fail("malformed CSV produced no error message")

    print("PASS: dynamic headers, stdout JSON, optional output file, missing "
          "file and malformed CSV are handled")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
