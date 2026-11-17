"""Behavior acceptance for the hello-world prompt.

The prompt is intentionally architecture-free.  The generated program may be
the normal CLI package or the generator's direct `app.py` fallback, so this
test finds the entry point rather than assuming one.

Run after extraction and generation::

    python3.12 tests/e2e_hello_acceptance.py out/hello_same_conditions
"""

import subprocess
import sys
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


def run(script):
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=str(script.parent), check=False, capture_output=True, text=True)


def main(argv):
    if len(argv) != 2:
        print("usage: e2e_hello_acceptance.py OUT_DIR", file=sys.stderr)
        return 2
    out_dir = Path(argv[1]).resolve()
    script = entrypoint(out_dir)
    source = script.read_text(encoding="utf-8")

    result = run(script)
    if result.returncode != 0:
        fail(f"{script} exited {result.returncode}: "
             f"{result.stdout + result.stderr!r}")
    if result.stdout.strip() != "Hello, World!":
        fail(f"expected 'Hello, World!', got {result.stdout!r}")

    if "def main(" not in source:
        fail("the generated program has no main() function")
    if "->" not in source:
        fail("the generated program has no type hints")
    if "__name__" not in source or "__main__" not in source:
        fail("the generated program has no __main__ guard")

    print("PASS: prints exactly Hello, World! and declares main(), type hints "
          "and the __main__ guard")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
