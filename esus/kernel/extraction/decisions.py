"""User-recorded answers to near-tied classifications.

`review_ties.py` asks about the ties `kernel.tie_rules` cannot resolve and
stores each answer here, in the output directory beside the documents. The
extractor re-applies them after classification on every run, so a human
decision survives reruns and the JSON stays stable; the review also patches
the on-disk document, so the current output is fixed without a rerun.

A decision record carries the classified text (the exact match key), the
chosen pattern id, and the candidates it was chosen from, so a stale answer —
for a text no run produces any more — is visible rather than silently applied.
It also carries the sha of the requirements it was decided under: answers are
only re-applied while the prompt is unchanged, because a reworded prompt can
move the meaning a text had. A record predating a prompt change is dropped
with a log line — the tie reopens and is re-asked — while records from before
hashes existed keep applying, having nothing to compare against.
"""

import hashlib
import json
from pathlib import Path

DECISIONS_NAME = "decisions.json"
DECISIONS_KEY = "decisions"
DECIDED = "decided"
DECIDED_BY_USER = "user"


def load_decisions(output_dir):
    """The recorded decisions, or [] when there are none or the file is unusable."""
    try:
        payload = json.loads((Path(output_dir) / DECISIONS_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    records = payload.get(DECISIONS_KEY)
    return [item for item in records] if isinstance(records, list) else []


def save_decisions(output_dir, decisions):
    """Write the decision records beside the documents."""
    path = Path(output_dir) / DECISIONS_NAME
    path.write_text(
        json.dumps({DECISIONS_KEY: decisions}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def requirements_sha(requirements_text):
    """The sha256 of a run's requirements, whitespace-normalized.

    Both sides normalize: `extract_arch.py` strips stdin but not the archived
    file, and the review reads the archived file — without this they would
    never agree.
    """
    if not isinstance(requirements_text, str):
        return None
    return hashlib.sha256(requirements_text.strip().encode("utf-8")).hexdigest()


def apply_decisions(matches, decisions, log=None, requirements_text=None):
    """Point every match whose text was decided at the chosen pattern.

    Returns a new list; unmatched entries and non-dicts pass through untouched,
    so applying an empty or stale record set is the identity. Each patched
    entry keeps its alternatives and gains `decision: decided` with
    `decided_by: user`, which is what stops the review from asking again.
    When `requirements_text` is given, a record stamped with a different
    prompt sha is dropped with a log line instead of applied: the tie reopens
    and the review asks again under the new prompt.

    A decision that *overrides* the recorded winner rewrites the whole
    verdict, not just the winner's name: the rejected side becomes the
    runner-up, and the margin and stage go, because a softmax gap against the
    rejected pattern cannot decide anything once a human has. Leaving the old
    runner-up in place would record the winner against itself — the exact
    `invalid_value` the checker reports. Keeping the recorded winner only
    stamps the flags; the entry is already coherent.
    """
    if not isinstance(matches, list):
        return matches
    current = requirements_sha(requirements_text) if requirements_text else None
    chosen = {}
    for record in decisions or []:
        if not (isinstance(record, dict)
                and isinstance(record.get("text"), str)
                and isinstance(record.get("chosen_pattern_id"), str)):
            continue
        stamped = record.get("requirements_sha")
        if (current is not None and isinstance(stamped, str)
                and stamped != current):
            if log is not None:
                log.write(
                    f"[!] step patterns: decision for '{record['text'][:60]}' "
                    f"predates a prompt change — dropped, will be re-asked"
                )
            continue
        chosen[record["text"]] = record["chosen_pattern_id"]
    if not chosen:
        return matches
    applied = 0
    patched = []
    for entry in matches:
        if (
            isinstance(entry, dict)
            and isinstance(entry.get("text"), str)
            and entry.get("text") in chosen
        ):
            winner = chosen[entry["text"]]
            update = {"pattern_id": winner,
                      "decision": DECIDED, "decided_by": DECIDED_BY_USER,
                      "undecided_stage": None}
            if winner != entry.get("pattern_id"):
                # Overridden: the recorded winner is the rejected side now.
                update["runner_up_pattern_id"] = entry.get("pattern_id")
                update["runner_up_confidence"] = entry.get("confidence")
                update["margin"] = None
            patched.append({**entry, **update})
            applied += 1
        else:
            patched.append(entry)
    if applied and log is not None:
        log.write(f"[ok] step patterns: applied {applied} recorded user decision(s)")
    return patched
