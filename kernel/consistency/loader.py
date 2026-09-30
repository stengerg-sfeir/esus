"""Safe loading of the per-step extraction documents.

"Safe" means one unusable file never aborts the run: a missing, unreadable,
malformed or wrongly shaped document becomes a finding and is skipped, so the
remaining checks still run and the report is still produced.
"""

import json
from dataclasses import dataclass
from pathlib import Path

# Steps A-E always run; steps G and H are skipped for prompts without persistence.
CORE_DOCUMENTS = (
    "intentions",
    "invariants",
    "data_models",
    "components",
    "service_contracts",
)
OPTIONAL_DOCUMENTS = ("interaction_adapters", "persistence_ports")
DOCUMENT_NAMES = CORE_DOCUMENTS + OPTIONAL_DOCUMENTS

LIST_DOCUMENTS = (
    "intentions",
    "invariants",
    "data_models",
    "service_contracts",
    "interaction_adapters",
)


@dataclass
class Documents:
    """The loaded document bodies, plus the names of the absent ones."""

    bodies: dict
    missing: tuple = ()

    def get(self, name, default=None):
        return self.bodies.get(name, default)


def load_documents(output_dir, report):
    """Load every extraction document in `output_dir`.

    Each body is the value under the document's own top-level key:
    data_models.json holds {"data_models": [...]} and yields the array.
    """
    directory = Path(output_dir)
    if not directory.is_dir():
        report.error("missing_directory", f"Output directory not found: {output_dir}")
        return Documents({}, tuple(DOCUMENT_NAMES))

    bodies = {}
    missing = []

    for name in DOCUMENT_NAMES:
        path = directory / f"{name}.json"
        if not path.is_file():
            if name in OPTIONAL_DOCUMENTS:
                missing.append(name)
            else:
                report.error("missing_document", f"MISSING: {path.name}")
            continue

        body = _read_document(path, name, report)
        if body is not None:
            bodies[name] = body

    return Documents(bodies, tuple(missing))


def _read_document(path, name, report):
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        report.error("malformed_document", f"UNREADABLE: {path.name}: {error}")
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        report.error(
            "malformed_document",
            f"MALFORMED: {path.name}: {error.msg} (line {error.lineno}, column {error.colno})",
        )
        return None

    if not isinstance(payload, dict):
        report.error(
            "unexpected_shape",
            f"UNEXPECTED SHAPE: {path.name} should hold a JSON object, "
            f"found {type(payload).__name__}",
        )
        return None

    if name not in payload:
        keys = ", ".join(sorted(payload)) or "none"
        report.error(
            "unexpected_shape",
            f"UNEXPECTED SHAPE: {path.name} has no '{name}' key (found: {keys})",
        )
        return None

    extra_keys = sorted(set(payload) - {name})
    if extra_keys:
        report.warning(
            "unexpected_shape",
            f"UNEXPECTED SHAPE: {path.name} carries unexpected key(s): {', '.join(extra_keys)}",
        )

    body = payload[name]
    expected_type = list if name in LIST_DOCUMENTS else dict
    if not isinstance(body, expected_type):
        kind = "array" if expected_type is list else "object"
        report.error(
            "unexpected_shape",
            f"UNEXPECTED SHAPE: {path.name}['{name}'] should be a JSON {kind}, "
            f"found {type(body).__name__}",
        )
        return None

    return body
