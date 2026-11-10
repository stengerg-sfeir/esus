"""Small acceptance-test harness for the direct GPT-6 Luna outputs.

The suites in this directory are deliberately independent of the generated
projects' own tests.  They drive the public CLI or service surface and use
fresh SQLite files, in the same style as ``tests/e2e_*_acceptance.py`` for the
ESUS outputs.

Run one suite with the interpreter under test::

    python3.12 tests/chatgpt_acceptance/inventory.py out/chatgpt_compare/inventory

``run_all.py`` runs every suite and writes a combined result file.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable


class CheckFailed(AssertionError):
    """A failed acceptance check."""


def fail(message: str) -> None:
    raise CheckFailed(message)


def require(condition: Any, message: str) -> None:
    if not condition:
        fail(message)


def equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        fail(f"{label}: expected {expected!r}, got {actual!r}")


def contains(text: str, needle: str, label: str) -> None:
    if needle not in text:
        fail(f"{label}: {needle!r} is missing from {text!r}")


def raises(expected: type[BaseException] | tuple[type[BaseException], ...],
           function: Callable[[], Any], label: str) -> BaseException:
    try:
        function()
    except expected as error:
        return error
    except BaseException as error:  # noqa: BLE001 - report the wrong failure
        fail(f"{label}: raised {type(error).__name__}: {error}")
    fail(f"{label}: operation was accepted")


def run_python(cwd: Path, args: list[str], *, expected: int = 0,
               env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = dict(os.environ)
    merged["PYTHONDONTWRITEBYTECODE"] = "1"
    if env:
        merged.update(env)
    result = subprocess.run(
        [sys.executable, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=merged,
        timeout=60,
    )
    if expected is not None and result.returncode != expected:
        fail(
            f"command {args!r} returned {result.returncode}, expected {expected}; "
            f"stdout={result.stdout!r}; stderr={result.stderr!r}"
        )
    return result


def run_cli(cwd: Path, args: list[str], *, expected: int = 0,
            env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return run_python(cwd, args, expected=expected, env=env)


def clean_error(result: subprocess.CompletedProcess[str], label: str) -> None:
    text = result.stdout + result.stderr
    require(bool(text.strip()), f"{label}: no error message")
    require("Traceback (most recent call last)" not in text,
            f"{label}: leaked a traceback: {text!r}")


def connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def fetchone(path: str | Path, sql: str, params: tuple = ()) -> sqlite3.Row:
    with connect(path) as connection:
        row = connection.execute(sql, params).fetchone()
    require(row is not None, f"query returned no row: {sql}")
    return row


def fetchall(path: str | Path, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with connect(path) as connection:
        return connection.execute(sql, params).fetchall()


def table_columns(path: str | Path, table: str) -> dict[str, sqlite3.Row]:
    with connect(path) as connection:
        return {row["name"]: row for row in connection.execute(
            f'PRAGMA table_info("{table}")')}


class Suite:
    """Collect checks, run them, and persist a JSON result document."""

    def __init__(self, name: str, out_dir: str | Path) -> None:
        self.name = name
        self.out = Path(out_dir).resolve()
        self.temp = tempfile.TemporaryDirectory(prefix=f"chatgpt-{name}-")
        self.temp_dir = Path(self.temp.name)
        self.checks: list[tuple[str, Callable[["Suite"], str | None]]] = []

    def check(self, name: str):
        def register(function: Callable[["Suite"], str | None]):
            self.checks.append((name, function))
            return function
        return register

    def path(self, name: str) -> Path:
        return self.temp_dir / name

    def db(self, name: str = "acceptance.sqlite3") -> Path:
        return self.path(name)

    def import_from(self, root: str | Path, package: str):
        root = str(Path(root).resolve())
        if root not in sys.path:
            sys.path.insert(0, root)
        import importlib
        return importlib.import_module(package)

    def run(self) -> int:
        results = []
        failures = 0
        for name, function in self.checks:
            try:
                note = function(self)
            except Exception as error:  # noqa: BLE001 - acceptance reports all
                failures += 1
                detail = f"{type(error).__name__}: {error}"
                results.append({"name": name, "status": "failed", "error": detail})
                print(f"FAIL  {name}: {detail}", file=sys.stderr)
            else:
                results.append({"name": name, "status": "passed", "note": note or ""})
                print(f"PASS  {name}" + (f": {note}" if note else ""))
        payload = {
            "status": "passed" if failures == 0 else "failed",
            "suite": self.name,
            "generated": str(self.out),
            "interpreter": sys.version,
            "checks": results,
        }
        try:
            (self.out / f"chatgpt_{self.name}_results.json").write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass
        if failures:
            print(f"{failures} of {len(self.checks)} checks failed", file=sys.stderr)
            return 1
        print(f"{len(self.checks)} of {len(self.checks)} checks passed")
        return 0

    def close(self) -> None:
        self.temp.cleanup()


def main(name: str, out_dir: str | None, run: Callable[[Suite], int]) -> int:
    if not out_dir:
        print(f"usage: {Path(sys.argv[0]).name} OUT_DIR", file=sys.stderr)
        return 2
    suite = Suite(name, out_dir)
    try:
        if not suite.out.is_dir():
            print(f"FAIL  output directory does not exist: {suite.out}", file=sys.stderr)
            return 2
        return run(suite)
    finally:
        suite.close()
