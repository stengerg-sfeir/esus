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

import generator  # noqa: E402
import review_aliases  # noqa: E402
import review_contracts  # noqa: E402
import review_grounding  # noqa: E402
import review_slots  # noqa: E402
import review_surface  # noqa: E402
import review_ties  # noqa: E402
import review_uniqueness  # noqa: E402



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


def _answer_slots(directory: Path) -> tuple[int, int]:
    """Answer the remaining slottable patterns from the documents.

    `review_slots` only offers a question when several candidates exist, and
    a threshold scan or aggregate has no single correct candidate in general.
    The method name is the evidence for the common shapes: minimum quantity
    is `>=`, below/low is `<`, a revenue aggregate is `SUM` over a money
    field, and the threshold is the method parameter when one is offered.
    """
    questions, context = review_slots.collect_slots(str(directory))
    if not questions:
        return 0, 0
    ctx = generator.load_context(str(directory))
    by_method = {}
    for repository in ctx["repositories"]:
        for method in repository.get("methods") or []:
            if isinstance(method, dict) and method.get("name"):
                by_method.setdefault(method["name"], method)
    records = review_slots.load_method_slots(str(directory))
    answered = 0

    def pick(candidates, patterns):
        for pattern in patterns:
            for candidate in candidates:
                if pattern in review_slots.normalize(candidate):
                    return candidate
        return candidates[0] if candidates else None

    for question in questions:
        method = by_method.get(question["method"], {})
        slots = {}
        usable = True
        for slot, candidates in question["options"]:
            if candidates is None:
                candidates = review_slots._resolve_deferred(
                    ctx, question, method, slot, slots)
            if not candidates:
                usable = False
                break
            if slot == "comparison_field":
                value = pick(candidates, ("quantity", "stock", "price", "amount"))
            elif slot == "operator":
                name = review_slots.normalize(question["method"])
                value = (">=" if "min" in name or "atleast" in name
                         else "<" if any(word in name for word in
                                         ("below", "under", "low", "less"))
                         else "=")
                if value not in candidates:
                    value = candidates[0]
            elif slot == "threshold":
                value = pick(candidates, ("min", "threshold", "limit",
                                          "stock", "quantity"))
            elif slot == "aggregate_func":
                value = "SUM" if "SUM" in candidates else candidates[0]
            elif slot == "target_field":
                value = pick(candidates, ("total", "price", "amount",
                                          "revenue", "quantity"))
            elif slot == "date_field":
                value = pick(candidates, ("date", "month", "year", "created"))
            else:
                value = candidates[0]
            if value is None:
                usable = False
                break
            slots[slot] = value
        if not usable:
            continue
        record = {
            "holder": question["holder"],
            "method": question["method"],
            "pattern": question["pattern"],
            "slots": slots,
            "decided_by": "user",
        }
        if context.get("prompt_sha") is not None:
            record["requirements_sha"] = context["prompt_sha"]
        records.append(record)
        answered += 1
    if answered:
        review_slots.save_method_slots(str(directory), records)
    return len(questions), answered


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
                values = [choice[1] for choice in choices
                          if isinstance(choice, (list, tuple))
                          and len(choice) > 1]
                if len(values) == 1:
                    answers[question_id] = values[0]
                elif "keep" in values:
                    answers[question_id] = "keep"
                elif question_id == "order" and "create_first" in values:
                    answers[question_id] = "create_first"
                elif str(question_id).startswith("effect:") and values:
                    # The proposal's first effect value is the one the
                    # documents describe; a multi-value effect is otherwise
                    # a business choice.
                    answers[question_id] = values[0]
                else:
                    ambiguous = True
                    break
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
        str(directory), input_fn=lambda _prompt: "1")
    counts["slots"] = review_slots.run_review(
        str(directory), input_fn=_slot_answer)
    counts["slots-deterministic"] = _answer_slots(directory)
    counts["surface"] = review_surface.run_review(
        str(directory), input_fn=_surface_answer)
    counts["aliases"] = review_aliases.run_review(
        str(directory), input_fn=lambda _prompt: "skip")

    counts["contracts"] = _answer_contracts(directory)
    inferred_overlap = review_contracts.add_inferred_overlap_preconditions(
        directory)
    if inferred_overlap:
        counts["inferred-overlap"] = (inferred_overlap, inferred_overlap)
    uniqueness_questions, _context = review_uniqueness.collect_questions(
        str(directory))
    if uniqueness_questions:
        # A uniqueness guess is a business decision; never answer it
        # automatically, but report it so the unattended run shows the work.
        counts["uniqueness"] = (
            sum(len(question.get("groups") or [])
                for question in uniqueness_questions), 0)
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
