#!/usr/bin/env python3
"""Record deterministic answers for the review questions in a validation tree.

The validation bench stores the extraction documents, not a human at a
terminal.  This pass only records answers that are actually forced by the
documents: a singleton slot candidate is usable, while a choice between
several methods, fields, routes or contract values stays open.  Surface drops
and upstream gaps are never decided automatically.  Every answer still goes
through the normal review writer and is stored in its normal sidecar, so a
human can finish the remaining questions later.

Usage:
    python scripts/answer_reviews.py out/validation/bench
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import review_aliases  # noqa: E402
import review_contracts  # noqa: E402
import review_grounding  # noqa: E402
import review_slots  # noqa: E402
import review_surface  # noqa: E402
import review_ties  # noqa: E402



def _surface_answer(_prompt):
    """Do not choose a surface route or drop a flag automatically.

    A dead option with no candidate can look harmless to drop, but it may be
    a required flag whose extraction was incomplete. A route with several
    candidates is a business decision. Both stay open for the attended
    review; only a single, explicitly evidenced route may be automated later.
    """
    return "skip"


def _slot_answer(prompt):
    """Answer a slot only when the offered candidate set is a singleton."""
    if "[" not in prompt or "]" not in prompt:
        return "skip"
    shown = prompt.split("[", 1)[1].split("]", 1)[0]
    candidates = [item.strip() for item in shown.split(",") if item.strip()]
    return "1" if len(candidates) == 1 else "skip"


def _grounding_answer(_prompt, default):
    """Keep the default answer, as a boolean.

    `review_grounding` treats any truthy reply as a drop. Returning the
    literal default string made its conservative `"n"` truthy and dropped
    every unsupported service. The default is the safe answer here: keep the
    evidence unless the attended reviewer explicitly says otherwise.
    """
    if isinstance(default, bool):
        return default
    return str(default).strip().lower() in ("y", "yes", "true", "1")


def _answer_contracts(directory: Path) -> tuple[int, int]:
    """Answer contract questions proposal by proposal.

    The review normally consumes a flat stdin; this caller needs to know
    which proposal a question belongs to so that an optional error check can
    be skipped without shifting the next proposal's answers.
    """
    proposals, context = review_contracts.collect_contracts(str(directory))
    if not proposals:
        return 0, 0
    records, _dropped = review_contracts.contract_rules.load_method_contracts(
        str(directory), review_contracts.load_requirements(str(directory)))
    ctx = review_contracts.generator.load_context(str(directory))
    answered = 0
    for proposal in proposals:
        answers = {}
        ambiguous = False
        # A proposal with any non-singleton choice or free-form effect stays
        # unanswered; the attended review must decide it.
        for question in proposal.get("questions") or []:
            question_id = question.get("id")
            if question.get("kind") == "choice":
                choices = question.get("choices") or []
                if len(choices) != 1:
                    ambiguous = True
                    break
                answers[question_id] = choices[0][1]
            elif question.get("required"):
                # A free-form effect operand or status is a business choice;
                # do not invent one deterministically.
                ambiguous = True
                break
            else:
                answers[question_id] = None
        if ambiguous:
            continue
        record = review_contracts._finalize(
            proposal, answers, context["prompt_sha"], ctx)
        if record is None:
            continue
        records = [item for item in records
                   if (item.get("holder"), item.get("method"))
                   != (record["holder"], record["method"])]
        records.append(record)
        answered += 1
    review_contracts.contract_rules.save_method_contracts(str(directory), records)
    return len(proposals), answered


def _drop_upstream_gaps(_directory: Path) -> int:
    """Never turn an upstream extraction gap into a surface drop.

    An absent model relationship is a document defect. Dropping the flag
    hides that defect and can remove a required capability; it stays for the
    attended review or the extraction repair.
    """
    return 0


def review_one(directory: Path) -> dict[str, tuple[int, int]]:
    counts = {}
    counts["grounding"] = review_grounding.run_review(
        str(directory), ask=_grounding_answer)
    counts["ties"] = review_ties.run_review(
        str(directory), input_fn=lambda _prompt: "skip")
    counts["slots"] = review_slots.run_review(
        str(directory), input_fn=_slot_answer)
    counts["surface"] = review_surface.run_review(
        str(directory), input_fn=_surface_answer)
    counts["aliases"] = review_aliases.run_review(
        str(directory), input_fn=lambda _prompt: "skip")

    counts["contracts"] = _answer_contracts(directory)
    inferred = review_contracts.add_inferred_stock_effects(directory)
    if inferred:
        counts["inferred-stock-effects"] = (inferred, inferred)
    collection = review_contracts.add_inferred_collection_creates(directory)
    if collection:
        counts["inferred-collection-creates"] = (collection, collection)
    records = review_contracts.add_inferred_record_creates(directory)
    if records:
        counts["inferred-record-creates"] = (records, records)
    return counts


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(__doc__.splitlines()[0], file=sys.stderr)
        print("usage: python scripts/answer_reviews.py OUT_DIR", file=sys.stderr)
        return 2
    root = Path(args[0])
    directories = sorted(path for path in root.glob("prompt_*") if path.is_dir())
    if not directories:
        print(f"no prompt directories under {root}", file=sys.stderr)
        return 2
    for directory in directories:
        counts = review_one(directory)
        answered = sum(answered for _asked, answered in counts.values())
        asked = sum(asked for asked, _answered in counts.values())
        print(f"{directory.name}: {answered}/{asked} review answer(s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
