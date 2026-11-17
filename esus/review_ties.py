#!/usr/bin/env python3
"""Ask the user about the near-tied classifications that change the generated body.

Step F records `decision: undecided` when the top two answers were too close to
call. Ties whose sides compile to the same body are resolved by rule
(`kernel.tie_rules`); the rest — a guard means a different check, and neither
the classifier nor the generator knows which failure the requirement means —
are questions for the requirements author, and this is where they are asked.

Usage:
    python review_ties.py out/library

Each open question shows the text, the source, both candidates with confidence
and margin, and the concrete alternative where one exists. Answers persist in
`decisions.json` beside the documents and are re-applied on every extraction
run, so one answer settles the tie permanently; the on-disk document is
patched too, so no rerun is needed. `skip` leaves a question open.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kernel import tie_rules  # noqa: E402
from kernel.consistency.loader import load_requirements  # noqa: E402
from kernel.extraction.decisions import (  # noqa: E402
    apply_decisions,
    load_decisions,
    requirements_sha,
    save_decisions,
)


def collect_questions(matches, decided_texts):
    """Every tie needing a human that has no recorded answer yet."""
    return [
        entry for entry in matches
        if tie_rules.needs_user(entry) and entry.get("text") not in decided_texts
    ]


def describe_question(index, total, entry):
    """The lines presenting one tie: text, source, and both sides."""
    lines = [
        f"--- question {index}/{total} ---",
        f"text:   {entry.get('text')}",
        f"source: {entry.get('source')}",
        f"1) recorded:   {entry.get('pattern_id')} "
        f"(confidence {entry.get('confidence')})",
    ]
    claimed = entry.get("claimed_pattern_id")
    recorded = entry.get("pattern_id")
    if isinstance(claimed, str) and claimed.strip() and claimed != recorded:
        # A shape correction explains a confidence that otherwise looks wrong:
        # the model's original answer was impossible for the return type, so
        # the recorded pattern is the best *viable* one, not the model's first
        # choice. Without this line, a tiny corrected probability prints as
        # `confidence 0.0` and reads like a broken classifier.
        claimed_confidence = entry.get("claimed_confidence")
        suffix = (f" (confidence {claimed_confidence})"
                  if claimed_confidence is not None else "")
        lines.append(f"   corrected from: {claimed}{suffix}")
        rejection = entry.get("rejection")
        if isinstance(rejection, str) and rejection.strip():
            lines.append(f"   reason: {rejection}")
        if entry.get("confidence") == 0.0:
            lines.append("   note: the recorded confidence is below 0.0001 "
                         "and rounds to 0.0.")
    alternative = tie_rules.alternative_of(entry)
    if alternative is not None:
        lines.append(f"2) alternative: {alternative}")
    else:
        lines.append(
            "2) alternative: (no concrete pattern — the other domain was never "
            "classified; keep 1 or skip)"
        )
    if entry.get("margin") is not None:
        lines.append(f"margin: {entry.get('margin')}")
    if entry.get("domain_margin") is not None:
        lines.append(f"domain margin: {entry.get('domain_margin')}")
    return lines


def ask(entry, input_fn=input):
    """Pose one tie; return the chosen pattern id, or None on skip/invalid."""
    alternative = tie_rules.alternative_of(entry)
    try:
        answer = input_fn("choose 1, 2, or skip: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    if answer in ("1", "keep", "recorded"):
        return entry.get("pattern_id")
    if answer in ("2", "alternative") and isinstance(alternative, str):
        return alternative
    return None


def run_review(output_dir, input_fn=input, out_fn=print):
    """Ask every open question; return (asked, answered)."""
    matches_path = os.path.join(output_dir, "pattern_matches.json")
    try:
        with open(matches_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as error:
        out_fn(f"error: cannot read {matches_path}: {error}")
        return 0, 0
    matches = payload.get("pattern_matches")
    if not isinstance(matches, list):
        out_fn(f"error: {matches_path} has no 'pattern_matches' list")
        return 0, 0

    decisions = load_decisions(output_dir)
    decided_texts = {
        record.get("text") for record in decisions if isinstance(record, dict)
    }
    prompt_sha = requirements_sha(load_requirements(output_dir))
    questions = collect_questions(matches, decided_texts)
    if not questions:
        out_fn("no open tie questions — nothing to decide")
        return 0, 0

    answered = 0
    for number, entry in enumerate(questions, start=1):
        for line in describe_question(number, len(questions), entry):
            out_fn(line)
        chosen = ask(entry, input_fn)
        if not isinstance(chosen, str):
            out_fn("skipped — left open")
            continue
        candidates = [entry.get("pattern_id"), tie_rules.alternative_of(entry)]
        record = {
            "text": entry.get("text"),
            "chosen_pattern_id": chosen,
            "candidates": [name for name in candidates if isinstance(name, str)],
            "decided_by": "user",
        }
        if prompt_sha is not None:
            # Without the stamp, a later prompt edit would keep applying an
            # answer given under different words. Missing requirements (a
            # hand-made directory) simply record no stamp.
            record["requirements_sha"] = prompt_sha
        decisions.append(record)
        answered += 1

    save_decisions(output_dir, decisions)
    with open(matches_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["pattern_matches"] = apply_decisions(payload.get("pattern_matches"), decisions)
    with open(matches_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    out_fn(f"answered {answered} of {len(questions)}; decisions in decisions.json")
    return len(questions), answered


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(__doc__.splitlines()[0], file=sys.stderr)
        print("usage: python review_ties.py OUT_DIR", file=sys.stderr)
        return 2
    asked, _ = run_review(args[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
