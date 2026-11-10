"""Acceptance checks for the direct GPT-6 Luna CSV-to-JSON CLI."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from common import (
    Suite, clean_error, contains, equal, main, require, run_python,
)


def write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def invoke(suite: Suite, *args: str, expected: int = 0):
    return run_python(suite.out, ["app.py", *args], expected=expected)


def run(suite: Suite) -> int:
    @suite.check("uses arbitrary headers dynamically")
    def dynamic_headers(_: Suite) -> str:
        source = suite.path("people.csv")
        write_csv(source, ["full name", "favourite colour"], [["Ada Lovelace", "blue"]])
        result = invoke(suite, str(source))
        rows = json.loads(result.stdout)
        equal(rows, [{"full name": "Ada Lovelace", "favourite colour": "blue"}],
              "JSON rows")
        return "spaces in headers preserved"

    @suite.check("preserves Unicode and quoted CSV values")
    def unicode_rows(_: Suite) -> str:
        source = suite.path("unicode.csv")
        write_csv(source, ["naïve", "note"], [["José", "a, b"], ["Zoë", 'say "hi"']])
        rows = json.loads(invoke(suite, str(source)).stdout)
        equal(rows, [{"naïve": "José", "note": "a, b"},
                     {"naïve": "Zoë", "note": 'say "hi"'}], "Unicode rows")
        return "Unicode and commas"

    @suite.check("supports a quoted newline inside a field")
    def multiline_field(_: Suite) -> str:
        source = suite.path("multiline.csv")
        source.write_text('key,value\none,"line 1\nline 2"\n', encoding="utf-8")
        rows = json.loads(invoke(suite, str(source)).stdout)
        equal(rows, [{"key": "one", "value": "line 1\nline 2"}], "multiline row")
        return "multiline field preserved"

    @suite.check("header-only CSV produces an empty JSON array")
    def header_only(_: Suite) -> str:
        source = suite.path("header-only.csv")
        write_csv(source, ["alpha", "beta"], [])
        rows = json.loads(invoke(suite, str(source)).stdout)
        equal(rows, [], "empty JSON list")
        return "[]"

    @suite.check("optional output file is written and stdout stays empty")
    def output_file(_: Suite) -> str:
        source = suite.path("source.csv")
        target = suite.path("result.json")
        write_csv(source, ["a", "b"], [["1", "2"]])
        result = invoke(suite, str(source), str(target))
        require(result.stdout.strip() == "", f"stdout not empty: {result.stdout!r}")
        equal(json.loads(target.read_text(encoding="utf-8")),
              [{"a": "1", "b": "2"}], "output file contents")
        return "file mode"

    @suite.check("overwrites an existing output file")
    def overwrite(_: Suite) -> str:
        source = suite.path("overwrite.csv")
        target = suite.path("overwrite.json")
        target.write_text("old contents", encoding="utf-8")
        write_csv(source, ["x"], [["new"]])
        invoke(suite, str(source), str(target))
        equal(json.loads(target.read_text(encoding="utf-8")), [{"x": "new"}],
              "overwritten file")
        return "overwrite"

    @suite.check("missing input fails cleanly")
    def missing_input(_: Suite) -> str:
        result = invoke(suite, str(suite.path("does-not-exist.csv")), expected=1)
        clean_error(result, "missing input")
        return "clean nonzero"

    @suite.check("malformed UTF-8 input fails cleanly")
    def invalid_utf8(_: Suite) -> str:
        source = suite.path("bad-utf8.csv")
        source.write_bytes(b"\xff\xfe\x00\x01not text")
        result = invoke(suite, str(source), expected=1)
        clean_error(result, "malformed input")
        return "clean nonzero"

    @suite.check("malformed row width fails cleanly")
    def malformed_width(_: Suite) -> str:
        source = suite.path("bad-width.csv")
        source.write_text("a,b\n1\n", encoding="utf-8")
        result = invoke(suite, str(source), expected=1)
        clean_error(result, "row width")
        return "clean nonzero"

    @suite.check("duplicate header names are rejected, not silently collapsed")
    def duplicate_headers(_: Suite) -> str:
        source = suite.path("duplicate.csv")
        source.write_text("name,name\none,two\n", encoding="utf-8")
        result = invoke(suite, str(source), expected=1)
        clean_error(result, "duplicate headers")
        return "clean nonzero"

    return suite.run()


if __name__ == "__main__":
    raise SystemExit(main("cli_tool", sys.argv[1] if len(sys.argv) > 1 else None, run))
