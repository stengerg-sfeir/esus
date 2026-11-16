#!/usr/bin/env python3
"""Record deterministic answers for the review questions in a validation tree.

The validation bench stores the extraction documents, not a human at a
terminal.  This pass answers the finite questions the review scripts offer,
using conservative defaults: keep the recorded classifier, keep both surface
nodes, choose the first enumerated slot, keep declared contracts, and keep
grounding evidence.  Every answer still goes through the normal review writer
and is stored in its normal sidecar, so the generated program is reproducible
and a human can replace any decision later.

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
from kernel.consistency.loader import load_requirements  # noqa: E402
from kernel.extraction.decisions import requirements_sha  # noqa: E402


def _surface_answer(prompt):
    prompt = prompt.strip().lower()
    if prompt.startswith("drop or skip"):
        return "drop"
    return "1"


def _contract_answers(proposals):
    """Flatten the answers in the exact order `ask_proposal` consumes them."""
    answers = []
    for proposal in proposals:
        for question in proposal.get("questions") or []:
            if question.get("kind") == "choice":
                choices = question.get("choices") or []
                answers.append(choices[0][1] if choices else "skip")
                continue
            target = str(question.get("effect") or "")
            if "order.status" in target:
                answers.append("'cancelled'")
            elif question.get("required"):
                # A required value with no enumerable option: keep the
                # generated expression valid rather than leave the contract
                # open. The review file records the choice for replacement.
                answers.append("1")
            else:
                answers.append("skip")
    return answers


def _drop_upstream_gaps(directory: Path) -> int:
    """Remove a dead flag whose upstream model relationship is absent.

    The review deliberately refuses to turn this into a surface decision: the
    right repair is the missing model field. For the bench, answering `drop`
    keeps the generated program runnable while the model gap remains visible
    in the review log.
    """
    routes, _context = review_surface.collect_routes(str(directory))
    gaps = [question for question in routes
            if isinstance(question, dict)
            and question.get("kind") == "upstream-gap"]
    if not gaps:
        return 0
    records = review_surface.load_surface_decisions(str(directory))
    existing = {(record.get("command"), record.get("subcommand"),
                 record.get("flag"))
                for record in records if isinstance(record, dict)}
    prompt_sha = requirements_sha(load_requirements(str(directory)))
    added = 0
    for question in gaps:
        key = (question.get("command"), question.get("subcommand"),
               question.get("flag"))
        if key in existing:
            continue
        record = {
            "kind": "drop-flag",
            "command": question["command"],
            "subcommand": question.get("subcommand"),
            "flag": question["flag"],
            "decided_by": "auto",
        }
        if prompt_sha is not None:
            record["requirements_sha"] = prompt_sha
        records.append(record)
        existing.add(key)
        added += 1
    if added:
        review_surface.save_surface_decisions(str(directory), records)
    return added


def review_one(directory: Path) -> dict[str, tuple[int, int]]:
    counts = {}
    counts["grounding"] = review_grounding.run_review(
        str(directory), ask=lambda _prompt, default: default)
    counts["ties"] = review_ties.run_review(
        str(directory), input_fn=lambda _prompt: "1")
    counts["slots"] = review_slots.run_review(
        str(directory), input_fn=lambda _prompt: "1")
    counts["surface"] = review_surface.run_review(
        str(directory), input_fn=_surface_answer)
    gap_drops = _drop_upstream_gaps(directory)
    if gap_drops:
        counts["upstream-gap-drops"] = (gap_drops, gap_drops)
    counts["aliases"] = review_aliases.run_review(
        str(directory), input_fn=lambda _prompt: "1")

    proposals, _context = review_contracts.collect_contracts(str(directory))
    queue = _contract_answers(proposals)

    def contract_input(_prompt):
        return queue.pop(0) if queue else "skip"

    counts["contracts"] = review_contracts.run_review(
        str(directory), input_fn=contract_input)
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
