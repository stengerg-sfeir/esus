"""Acceptance checks for the 2026-11-13 CSV-to-JSON CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from common import Suite, clean_error, equal, main, require, run_python


def csv_file(suite: Suite, name: str, text: str) -> Path:
    path = suite.path(name)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def run(suite: Suite) -> int:
    entry = suite.out / "csv_to_json.py"

    @suite.check("CSV-to-JSON entry point exists")
    def entrypoint(_: Suite) -> str:
        require(entry.is_file(), f"missing {entry}")
        return entry.name

    @suite.check("dynamic headers become JSON keys")
    def dynamic_headers(_: Suite) -> str:
        source = csv_file(suite, "dynamic.csv", "full name,age\nAda Lovelace,36\n")
        result = run_python(suite.out, [entry.name, str(source)])
        equal(json.loads(result.stdout), [{"full name": "Ada Lovelace", "age": "36"}], "JSON")
        return "dynamic keys"

    @suite.check("optional -o output file leaves stdout empty")
    def output_file(_: Suite) -> str:
        source = csv_file(suite, "output.csv", "title\nKindred\n")
        target = suite.path("result.json")
        result = run_python(suite.out, [entry.name, str(source), "-o", str(target)])
        equal(result.stdout, "", "stdout")
        equal(json.loads(target.read_text(encoding="utf-8")),
              [{"title": "Kindred"}], "file JSON")
        return "file mode"

    @suite.check("overwrites an existing output file")
    def overwrite(_: Suite) -> str:
        source = csv_file(suite, "overwrite.csv", "name\nNew\n")
        target = suite.path("overwrite.json")
        target.write_text("old", encoding="utf-8")
        run_python(suite.out, [entry.name, str(source), "-o", str(target)])
        equal(json.loads(target.read_text(encoding="utf-8")), [{"name": "New"}], "replaced")
        return "overwrite"

    @suite.check("preserves Unicode, commas, quotes and newlines")
    def values(_: Suite) -> str:
        source = csv_file(
            suite, "values.csv",
            'name,note\n"Émile, Zola","line one\nline two ""quoted"""\n',
        )
        result = run_python(suite.out, [entry.name, str(source)])
        equal(json.loads(result.stdout), [{
            "name": "Émile, Zola",
            "note": 'line one\nline two "quoted"',
        }], "values")
        return "Unicode and CSV quoting"

    @suite.check("header-only input produces an empty JSON array")
    def header_only(_: Suite) -> str:
        source = csv_file(suite, "empty.csv", "name,age\n")
        result = run_python(suite.out, [entry.name, str(source)])
        equal(json.loads(result.stdout), [], "empty array")
        return "empty array"

    @suite.check("missing input fails cleanly")
    def missing(_: Suite) -> str:
        result = run_python(suite.out, [entry.name, str(suite.path("absent.csv"))],
                            expected=1)
        clean_error(result, "missing file")
        return "clean nonzero"

    @suite.check("malformed UTF-8 fails cleanly")
    def bad_utf8(_: Suite) -> str:
        source = suite.path("bad-utf8.csv")
        source.write_bytes(b"name\n\xff\n")
        result = run_python(suite.out, [entry.name, str(source)], expected=1)
        clean_error(result, "malformed UTF-8")
        return "clean nonzero"

    @suite.check("mismatched row width fails cleanly")
    def row_width(_: Suite) -> str:
        source = csv_file(suite, "width.csv", "a,b\n1\n")
        result = run_python(suite.out, [entry.name, str(source)], expected=1)
        clean_error(result, "row width")
        return "clean nonzero"

    @suite.check("duplicate headers are rejected")
    def duplicate_headers(_: Suite) -> str:
        source = csv_file(suite, "duplicate.csv", "a,a\n1,2\n")
        result = run_python(suite.out, [entry.name, str(source)], expected=1)
        clean_error(result, "duplicate headers")
        return "clean nonzero"

    return suite.run()


if __name__ == "__main__":
    raise SystemExit(main("cli_tool", sys.argv[1] if len(sys.argv) > 1 else None, run))
