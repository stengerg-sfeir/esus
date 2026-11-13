"""Acceptance checks for the 2026-11-13 GPT-6 Luna hello-world output."""

from __future__ import annotations

import sys

from common import Suite, contains, equal, main, require, run_python


def run(suite: Suite) -> int:
    entry = suite.out / "hello.py"
    if not entry.is_file():
        entry = suite.out / "app.py"

    @suite.check("entry point exists")
    def entrypoint(_: Suite) -> str:
        require(entry.is_file(), f"missing hello.py/app.py in {suite.out}")
        return entry.name

    @suite.check("prints exactly Hello, World!")
    def output(_: Suite) -> str:
        result = run_python(suite.out, [entry.name])
        equal(result.stdout, "Hello, World!\n", "stdout")
        equal(result.stderr, "", "stderr")
        return result.stdout.strip()

    @suite.check("declares main() with a return annotation and __main__ guard")
    def structure(_: Suite) -> str:
        source = entry.read_text(encoding="utf-8")
        contains(source, "def main(", "main function")
        contains(source, '__name__ == "__main__"', "__main__ guard")
        require("->" in source, "no return annotation")
        return "main(), annotation and guard"

    @suite.check("exits cleanly")
    def clean_exit(_: Suite) -> str:
        result = run_python(suite.out, [entry.name], expected=0)
        require(result.returncode == 0, "nonzero exit")
        return "exit 0"

    return suite.run()


if __name__ == "__main__":
    raise SystemExit(main("hello", sys.argv[1] if len(sys.argv) > 1 else None, run))
