"""Writing the extracted documents and the run log.

The output directory holds one `<step>.json` per document, which is exactly the
layout `kernel.consistency.loader` reads, so a run and its check need no
renaming step in between.
"""

import json
import sys
import threading
from pathlib import Path

from kernel.extraction import ordering

RUN_LOG_NAME = "run.log"

# The requirements the run was given, written beside the documents so the checker
# can compare what the program *says* it accepts with what the requirements asked
# for. Nothing measured that before: `invocation` was checked against the parser
# technology and against itself, never against the prose it was extracted from,
# so a command the requirements name and the surface omits was invisible — which
# is exactly what happened to expenses, whose `category` and `budget` recorded no
# subcommands at all while the requirements name three each.
REQUIREMENTS_NAME = "requirements.txt"

# Every document a run may produce. A step that is skipped (step H when the
# components declare no persistence) must not leave the previous run's file
# behind, or the checker would report on a document this run never wrote.
DOCUMENT_NAMES = (
    "intentions",
    "invariants",
    "data_models",
    "components",
    "service_contracts",
    "interaction_adapters",
    "persistence_ports",
    "pattern_matches",
)


class RunLog:
    """Collects progress lines, echoing them to stderr and to run.log.

    With `quiet=True` the lines are still collected for `run.log` but not
    echoed: the caller prints its own concise summary instead, so a `--quiet`
    run shows steps and results while the full detail stays in the file.
    """

    def __init__(self, path=None, quiet=False):
        self.path = Path(path) if path else None
        self.lines = []
        self.quiet = quiet
        # Parallel extraction writes from more than one step at a time. The
        # lock keeps each line whole; it does not promise an order, because the
        # order in which concurrent model calls finish is not deterministic.
        self._lock = threading.Lock()

    def write(self, message):
        with self._lock:
            self.lines.append(message)
            if not self.quiet:
                print(message, file=sys.stderr)

    def flush(self):
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(self.lines) + "\n", encoding="utf-8")


def clear_documents(output_dir):
    """Remove any document left by an earlier run in this directory."""
    directory = Path(output_dir)
    for name in DOCUMENT_NAMES:
        path = directory / f"{name}.json"
        if path.is_file():
            path.unlink()


def write_requirements(output_dir, requirements):
    """Store the run's own requirements beside its documents."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / REQUIREMENTS_NAME
    path.write_text(requirements.strip() + "\n", encoding="utf-8")
    return path


def write_documents(output_dir, documents):
    """Write one `<name>.json` per document; return the paths written."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    clear_documents(directory)

    written = []
    for name, body in documents.items():
        path = directory / f"{name}.json"
        # The model chooses the content; the order of name-keyed collections
        # is presentation.  Canonicalising here makes two runs that extracted
        # the same facts write the same bytes, which is what lets a diff show
        # a real change instead of a reordering.  `sort_keys` does the same for
        # object members; list order is handled by `ordering`.
        body = ordering.canonicalize(name, body)
        payload = json.dumps({name: body}, indent=2, ensure_ascii=False,
                             sort_keys=True)
        path.write_text(payload + "\n", encoding="utf-8")
        written.append(path)
    return written
