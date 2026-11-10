"""Acceptance checks for the direct GPT-6 Luna hello-world output."""

from __future__ import annotations

import sys
from pathlib import Path

from common import Suite, contains, main, require, run_python


def run(suite: Suite) -> int:
    entry = suite.out / "app.py"

    @suite.check("app.py entry point exists")
    def entrypoint(_: Suite) -> str:
        require(entry.is_file(), f"missing {entry}")
        return "app.py"

    @suite.check("prints exactly Hello, World!")
    def output(_: Suite) -> str:
        result = run_python(suite.out, ["app.py"])
        require(result.stdout == "Hello, World!\n",
                f"unexpected stdout: {result.stdout!r}")
        require(result.stderr == "", f"unexpected stderr: {result.stderr!r}")
        return result.stdout.strip()

    @suite.check("declares main() and the __main__ guard")
    def structure(_: Suite) -> str:
        source = entry.read_text(encoding="utf-8")
        contains(source, "def main(", "main function")
        contains(source, '__name__ == "__main__"', "__main__ guard")
        require("->" in source, "no type annotation found")
        return "main(), annotation and guard"

    @suite.check("stays quiet on stderr and exits zero")
    def clean_exit(_: Suite) -> str:
        result = run_python(suite.out, ["app.py"])
        require(result.returncode == 0, f"exit {result.returncode}")
        require(not result.stderr.strip(), f"stderr: {result.stderr!r}")
        return "exit 0"

    return suite.run()


if __name__ == "__main__":
    raise SystemExit(main("hello", sys.argv[1] if len(sys.argv) > 1 else None, run))
