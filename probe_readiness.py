"""Is the extraction output ready for a code generator? Checks the documents directly.

The consistency checker proves the documents agree with each other. A generator
needs more: every command backed by a method, every adapter resolving, every
crud operation implemented by its own entity's interface, every parameter
well-typed, every raised error registered. This probe measures those, per
prompt, and prints the blockers a generator would have to paper over.

Implementation: this probe reuses kernel.consistency.check_directory as the
single definition of each defect (no duplicated stem tables), then classifies
findings into generator blockers vs consistency risks:

- blockers: every error + every warning + unbacked_command notes promoted to
  blockers (a CLI verb no method serves is a call the generator cannot write).
- risks: narrow_margin / low_confidence / missing_pattern / corrected_claim
  notes. They do not force invention, but they mean the JSON may differ
  between runs or name a vocabulary gap the generator must work around.

Exit code is 0 when no blocker was found and 1 otherwise, so CI can gate on it.
Usage:
    python probe_readiness.py [--dirs NAME:PATH ...]
    python probe_readiness.py   # checks out/<PROMPTS>
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kernel.consistency import check_directory  # noqa: E402
from kernel import tie_rules  # noqa: E402
from kernel import codegen as codegen_rules  # noqa: E402
from kernel.consistency.loader import load_documents  # noqa: E402
from kernel.consistency.report import Finding, Report  # noqa: E402

OUT = "out"
PROMPTS = ("hello", "cli_tool", "inventory", "gui", "expenses", "60", "library")

# Notes that do not force invention but mean the JSON may differ per run or
# name a pattern the catalogue lacks. Reported separately, never counted as
# blockers.
RISK_RULES = frozenset(
    {"narrow_margin", "low_confidence", "missing_pattern", "corrected_claim"}
)

# The one note the checker cannot call a defect (stem match only) but a
# generator cannot survive: a command with no method behind it.
PROMOTED_NOTES = frozenset({"unbacked_command"})


def open_questions(path):
    """Ties needing a human that have no recorded answer (`review_ties.py`)."""
    import json

    try:
        with open(os.path.join(path, "pattern_matches.json"), encoding="utf-8") as handle:
            matches = json.load(handle).get("pattern_matches")
    except (OSError, ValueError, AttributeError):
        return 0
    if not isinstance(matches, list):
        return 0
    return sum(1 for entry in matches if tie_rules.needs_user(entry))


def check_prompt(name, path):
    """Run the checker over one output directory; return (blockers, risks)."""
    report = check_directory(path, name)
    blockers = list(report.errors) + list(report.warnings)
    risks = []
    for note in report.notes:
        if note.rule in PROMOTED_NOTES:
            blockers.append(note)
        elif note.rule in RISK_RULES:
            risks.append(note)
    # Deterministic order: severity already split, sort by rule then message.
    blockers.sort(key=lambda f: (f.rule, f.message))
    risks.sort(key=lambda f: (f.rule, f.message))
    for action, field in uncovered_fields(path):
        blockers.append(Finding(
            "warning", "uncovered_field",
            f"interaction_adapters: '{action}' requires field '{field}' "
            f"but no CLI flag supplies it — the action parses but can never run"))
    for action, field, entity in unknown_model_fields(path):
        blockers.append(Finding(
            "warning", "unknown_model_field",
            f"interaction_adapters: '{action}' builds {entity} with '{field}', "
            f"which {entity} does not declare — construction always fails"))
    blockers.sort(key=lambda f: (f.rule, f.message))
    return blockers, risks, report


def uncovered_fields(path):
    """Required adapter fields no bound CLI flag can supply, as `(action, field)`.

    Non-CLI facades (a GUI takes no flags) and missing invocations have no
    flags by design and are skipped — the rule judges CLI surfaces only.
    """
    documents = load_documents(path, Report("probe"))
    facade = (documents.get("components") or {}).get("facade") or {}
    if facade.get("type") != "cli" or not isinstance(facade.get("invocation"), dict):
        return []
    models = documents.get("data_models") or []
    entity_names = [m.get("name") for m in models
                    if isinstance(m, dict) and m.get("name")]
    ports = documents.get("persistence_ports")
    repositories = []
    if isinstance(ports, dict) and isinstance(ports.get("repositories"), list):
        repositories = ports["repositories"]
    targets = codegen_rules.action_targets(
        documents.get("interaction_adapters") or [],
        documents.get("service_contracts") or [],
        repositories, entity_names)
    return codegen_rules.uncovered_required_fields(
        documents.get("interaction_adapters") or [], facade["invocation"], targets)


def unknown_model_fields(path):
    """Adapter fields assembling undeclared model fields, as `(action, field, entity)`."""
    documents = load_documents(path, Report("probe"))
    models = documents.get("data_models")
    ports = documents.get("persistence_ports")
    repositories = []
    if isinstance(ports, dict) and isinstance(ports.get("repositories"), list):
        repositories = ports["repositories"]
    return codegen_rules.unknown_model_fields(
        documents.get("interaction_adapters") or [],
        documents.get("service_contracts") or [],
        repositories, models or [])


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dirs",
        nargs="+",
        metavar="NAME:PATH",
        help="One or more output directories (format: name:path). "
        "Defaults to out/<PROMPTS>.",
    )
    return parser


def parse_dirs(entries):
    pairs = []
    for entry in entries:
        name, sep, path = entry.partition(":")
        if not sep or not name.strip() or not path.strip():
            raise argparse.ArgumentTypeError(
                f"expected 'NAME:PATH', got '{entry}'"
            )
        pairs.append((name.strip(), path.strip()))
    return pairs


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.dirs:
        targets = parse_dirs(args.dirs)
    else:
        targets = [(name, os.path.join(OUT, name)) for name in PROMPTS]

    total_blockers = 0
    total_risks = 0
    total_questions = 0
    for name, path in targets:
        if not os.path.isdir(path):
            print(f"{name:10} MISSING OUTPUT")
            continue
        blockers, risks, _ = check_prompt(name, path)
        questions = open_questions(path)
        total_blockers += len(blockers)
        total_risks += len(risks)
        total_questions += questions
        print(f"{name:10} {len(blockers)} blocker(s), {len(risks)} risk(s), "
              f"{questions} open tie(s)")
        for finding in blockers:
            print(f"           - [{finding.rule}] {finding.message}")
    print(f"\nTOTAL generator blockers: {total_blockers}")
    print(f"TOTAL consistency risks: {total_risks} (narrow/low/missing/corrected)")
    if total_questions:
        print(f"TOTAL open ties needing a human: {total_questions} "
              f"(python review_ties.py OUT_DIR)")
    return 1 if total_blockers else 0


if __name__ == "__main__":
    sys.exit(main())
