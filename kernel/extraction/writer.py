"""Writing the extracted documents and the run log.

The output directory holds one `<step>.json` per document, which is exactly the
layout `kernel.consistency.loader` reads, so a run and its check need no
renaming step in between.
"""

import json
import sys
from pathlib import Path

RUN_LOG_NAME = "run.log"

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
    """Collects progress lines, echoing them to stderr and to run.log."""

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.lines = []

    def write(self, message):
        self.lines.append(message)
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


def write_documents(output_dir, documents):
    """Write one `<name>.json` per document; return the paths written."""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    clear_documents(directory)

    written = []
    for name, body in documents.items():
        path = directory / f"{name}.json"
        payload = json.dumps({name: body}, indent=2, ensure_ascii=False)
        path.write_text(payload + "\n", encoding="utf-8")
        written.append(path)
    return written
