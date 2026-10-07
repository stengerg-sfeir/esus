"""Validation of step F's output, the one document nothing read.

`pattern_matches.json` is produced by step F and written to disk, but no check
ever loaded it: the classifier's output was unexamined, so a pattern id outside
the vocabulary passed silently.

The allowed ids come from `kernel.pattern_catalog` — the same dependency-free
module the classifier reads — so the two can never disagree about what a
`pattern_id` may be. Three of those ids are answers rather than patterns:

- `STANDARD_CRUD` — plain create/read/update/delete by key. Correct, expected,
  and **not** a finding: no named pattern describes it.
- `NO_MATCH` — fits no domain. A gap.
- `NO_PATTERN_IN_DOMAIN` — the domain fits, no pattern in it does. A gap.

The two gaps are reported as `missing_pattern`, one note each, and they are the
coverage report for the vocabulary: the texts that produce them say which pattern
is missing. `STANDARD_CRUD` is never reported, because it names nothing absent.

Three checks are structural and currently find nothing, and they are here as
guards rather than as findings: a `contract:<Service>.<method>` source must
resolve to a method the service contracts declare, `confidence` must be a number
in [0, 1], and an unknown `pattern_id` is still an `unknown_reference`.
"""

from kernel.consistency.methods import is_missing
from kernel.pattern_catalog import (
    GAP_PATTERN_IDS,
    NO_MATCH,
    SENTINEL_PATTERN_IDS,
    known_pattern_ids,
)

SOURCE_INVARIANT = "invariant"
SOURCE_CONTRACT = "contract"

# The confidence is the product of two softmaxes — the domain and then the
# pattern — so it is structurally lower than either stage alone: a confident
# 0.9 domain with a 0.7 pattern reports 0.63. A match below 0.2 therefore means
# both stages were unsure.
#
# Reported as a NOTE, not a warning, on the same reasoning as an empty section:
# the checker has no ground truth for the match, so it cannot tell a
# low-confidence-but-correct classification from a wrong one, and calling it a
# defect would assert something the checker cannot substantiate. Chosen from the
# corpus: 0.2 isolates five matches, while 0.5 would report 88 and bury them.
#
# Re-derive this floor whenever the option list changes: adding or removing
# answers moves probability mass, so every confidence shifts with it.
LOW_CONFIDENCE = 0.2

# How close the top two answers may be before the match is reported as
# undecided. `LOW_CONFIDENCE` above asks "was the winner unsure?", which cannot
# see the case this one exists for: a 0.70 that beat 0.69 is a coin-flip and a
# 0.70 that beat 0.05 is a decision, and both report 0.70. The margin between
# the winner and the runner-up is what separates them, and `pattern_matches`
# carries it (`runner_up_pattern_id`, `margin`) for exactly this check.
#
# This is the check that would have named the defect the floor could not: the
# same kind of requirement (`read_all_*`) landing on a gap in one prompt and on
# `FILTER_WITH_PAGINATION` in another was a near-tie reported as a decision.
# Calibrated against the corpus after the read-shape vocabulary was completed;
# re-derive it whenever the option list changes, as with the floor.
NARROW_MARGIN = 0.15

# Step 1's own threshold, on its own scale — a raw softmax gap, where `margin`
# below is that gap multiplied by the domain probability. It mirrors
# `classification.DOMAIN_NARROW_MARGIN` and **must be kept equal to it**; it is
# duplicated rather than imported because the checker may not import the
# extraction package, which reaches `llama_cpp` through the classifier. The same
# constraint already applies to `NARROW_MARGIN`.
DOMAIN_NARROW_MARGIN = 0.15

# The three decisions a match may carry, mirroring `classification`. Written as
# literals here for the same reason as the thresholds.
DECIDED = "decided"
UNDECIDED = "undecided"
UNDEFINED = "undefined"
DECISIONS = frozenset({DECIDED, UNDECIDED, UNDEFINED})

# Which stage was near-tied.
STAGE_DOMAIN = "domain"
STAGE_PATTERN = "pattern"


def check_pattern_matches(matches, documents, report):
    """Validate pattern_matches against the catalogues and the contracts."""
    if matches is None:
        return

    known = _known_pattern_ids(report)
    declared = _declared_methods(documents)

    for entry in matches:
        if not isinstance(entry, dict):
            report.error("invalid_value", "pattern_matches: an entry is not an object")
            continue
        _check_pattern_id(entry, known, report)
        _check_confidence(entry, report)
        _check_margin(entry, report)
        _check_claim(entry, report)
        _check_source(entry, declared, report)

    _report_gaps(matches, report)


def _report_gaps(matches, report):
    """One note per gap answer: the vocabulary's coverage report.

    `NO_MATCH` says no domain fits; `NO_PATTERN_IN_DOMAIN` says the domain fits
    but no pattern inside it does. Both name something the catalogue lacks, and
    each entry carries the text that produced it, so the notes answer "which
    pattern should be added next?" rather than merely scoring the run.

    `STANDARD_CRUD` is deliberately absent: it is the correct answer for ordinary
    CRUD, names nothing missing, and would otherwise drown the report with one
    note per repository method.
    """
    for entry in matches:
        if not isinstance(entry, dict):
            continue
        pattern_id = entry.get("pattern_id")
        if pattern_id not in GAP_PATTERN_IDS:
            continue
        reason = (
            "fits no domain"
            if pattern_id == NO_MATCH
            else "fits a domain but no pattern inside it"
        )
        # A gap that came from a refusal names the pattern the classifier wanted
        # and the evidence that ruled it out. That is the difference between a
        # coverage report and a shrug: "claimed AGGREGATE_BY_FK_AND_DATE, refused
        # because it returns collection" is a specification for the pattern to
        # add, which is what the gap exists to say.
        claimed = entry.get("claimed_pattern_id")
        rejection = entry.get("rejection")
        if rejection:
            detail = (
                f"the classifier claimed '{claimed}' and it was refused: {rejection} "
                f"— the catalogue has no pattern for a method of this shape"
            )
        else:
            detail = "no pattern covers it"
        report.note(
            "missing_pattern",
            f"pattern_matches: {entry.get('text')!r} {reason} — {detail} "
            f"('{pattern_id}', confidence {entry.get('confidence')})",
        )


def _check_pattern_id(entry, known, report):
    pattern_id = entry.get("pattern_id")
    if is_missing(pattern_id):
        report.warning("placeholder_value", "pattern_matches: an entry has no pattern_id")
        return
    if known is not None and pattern_id not in known:
        report.warning(
            "unknown_reference",
            f"pattern_matches: pattern_id '{pattern_id}' is in neither pattern catalogue",
        )


def _check_confidence(entry, report):
    confidence = entry.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        report.error(
            "invalid_value",
            f"pattern_matches: confidence should be a number, found {confidence!r}",
        )
        return
    if not 0 <= confidence <= 1:
        report.error(
            "invalid_value",
            f"pattern_matches: confidence {confidence} is outside [0, 1]",
        )
        return
    if entry.get("pattern_id") in SENTINEL_PATTERN_IDS:
        # A sentinel is already accounted for: a gap is reported by
        # `_report_gaps`, and `STANDARD_CRUD` is a legitimate answer. Its
        # confidence is a separate question, and flagging it here would report
        # the same entry twice under two different rules.
        return
    if confidence < LOW_CONFIDENCE:
        report.note(
            "low_confidence",
            f"pattern_matches: '{entry.get('pattern_id')}' matched {entry.get('text')!r} "
            f"at confidence {confidence:.2f} — below the {LOW_CONFIDENCE} floor",
        )


def _check_margin(entry, report):
    """Report a match whose top two answers were too close to call.

    Two categories the generator routes on, and the document now names both:
    `undefined` is a gap (reported by `_report_gaps`) and `undecided` is a
    near-tie, reported here. A `decided` match is not reported at all.

    **Two guards run before the note, because they are defects rather than
    signals:**

    - A `runner_up_pattern_id` equal to the recorded `pattern_id` is a margin
      computed against the winner. It can never move the answer, so the
      runner-up was mis-recorded — this is the bug that let three notes read
      `'FILTER_BY_FIELD' ... over 'FILTER_BY_FIELD'`, and it is reported as an
      error so it cannot return silently (`classification._runner_up`).
    - A `decision` outside the three known values is a shape error.

    Both stages are judged, and the **domain** stage first, because it decides
    which pattern list step 2 even saw: a near-tied domain means the pattern
    margin describes a choice among possibly-wrong options. A document written
    before the field existed still reports from the margin alone.
    """
    pattern_id = entry.get("pattern_id")
    runner_up = entry.get("runner_up_pattern_id")
    decision = entry.get("decision")
    if runner_up and runner_up == pattern_id:
        report.error(
            "invalid_value",
            f"pattern_matches: '{pattern_id}' matched {entry.get('text')!r} with itself "
            f"as the runner-up — a margin against the winner cannot decide anything",
        )
        return
    if decision is not None and decision not in DECISIONS:
        report.error(
            "unsupported_value",
            f"pattern_matches: decision {decision!r} is not one of "
            f"{sorted(DECISIONS)}",
        )
        return
    if pattern_id in GAP_PATTERN_IDS:
        # A gap is not a choice, so there are no two answers for a margin to
        # separate — a number here is a defect, not a signal. They came out large
        # and negative before this (`-0.48` on six of seven gaps), because the
        # figure compared the entry's own sentinel probability against the
        # claim's.
        if decision == UNDEFINED and entry.get("margin") is not None:
            report.error(
                "invalid_value",
                f"pattern_matches: '{pattern_id}' has no pattern but carries a margin of "
                f"{entry.get('margin')} — a gap is not a choice between two answers",
            )
        return

    if decision == DECIDED:
        return

    if decision == UNDECIDED:
        if entry.get("undecided_stage") == STAGE_DOMAIN:
            _report_domain_near_tie(entry, report)
        else:
            _report_pattern_near_tie(entry, report)
        return
    if decision == UNDEFINED:
        return

    # No `decision`: a document from before the field existed. Fall back to the
    # margin, and to the domain stage first for the same reason as above.
    domain_margin = entry.get("domain_margin")
    if _is_narrow(domain_margin, DOMAIN_NARROW_MARGIN):
        _report_domain_near_tie(entry, report)
        return
    if _is_narrow(entry.get("margin"), NARROW_MARGIN) and runner_up:
        _report_pattern_near_tie(entry, report)


def _is_narrow(margin, threshold):
    """True when a margin is a number below its threshold."""
    if not isinstance(margin, (int, float)) or isinstance(margin, bool):
        return False
    return margin < threshold


def _report_domain_near_tie(entry, report):
    """Step 1's top two domains were too close to call.

    Worth more than the pattern-stage note: the domain picks which pattern list
    step 2 is even shown, so a near-tie here is a choice between two *sets* of
    answers, and the recorded pattern is one of only one set's.
    """
    report.note(
        "narrow_margin",
        f"pattern_matches: the domains for {entry.get('text')!r} were too close to call — "
        f"'{entry.get('domain')}' beat '{entry.get('domain_runner_up')}' by "
        f"{entry.get('domain_margin')} — so the pattern chosen inside it may differ "
        f"between runs",
    )


def _report_pattern_near_tie(entry, report):
    """Step 2's top two patterns were too close to call."""
    report.note(
        "narrow_margin",
        f"pattern_matches: '{entry.get('pattern_id')}' matched {entry.get('text')!r} "
        f"by a margin of {entry.get('margin')} over '{entry.get('runner_up_pattern_id')}' "
        f"— the answer was near-tied, so it may differ between runs",
    )


def _check_claim(entry, report):
    """Note a match whose recorded pattern is not the one the classifier chose.

    The claim was impossible for the method's return type, so the next
    shape-compatible candidate replaced it (`kernel.extraction.classification`).
    The correction is deterministic and the recorded pattern is the right one, so
    this is a note and not a defect — but it is worth naming, because a run with
    many corrections is telling us the classifier reaches for an aggregate on a
    method that returns records, and that is a description to sharpen.

    A gap is skipped: `_report_gaps` already reports it, with the same claim.
    """
    rejection = entry.get("rejection")
    if not rejection:
        return
    pattern_id = entry.get("pattern_id")
    if pattern_id in GAP_PATTERN_IDS:
        return
    report.note(
        "corrected_claim",
        f"pattern_matches: {entry.get('text')!r} was claimed as "
        f"'{entry.get('claimed_pattern_id')}' and recorded as '{pattern_id}' — {rejection}",
    )


def _check_source(entry, declared, report):
    source = entry.get("source")
    if is_missing(source):
        report.warning("placeholder_value", "pattern_matches: an entry has no source")
        return
    if source == SOURCE_INVARIANT:
        return
    if not source.startswith(f"{SOURCE_CONTRACT}:"):
        report.error(
            "unsupported_value",
            f"pattern_matches: source '{source}' is neither '{SOURCE_INVARIANT}' "
            f"nor '{SOURCE_CONTRACT}:<Service>.<method>'",
        )
        return

    reference = source.split(":", 1)[1]
    if "." not in reference:
        report.error(
            "invalid_identifier",
            f"pattern_matches: source '{source}' does not name a service and a method",
        )
        return
    service, method = reference.rsplit(".", 1)
    if service not in declared:
        report.warning(
            "unknown_reference",
            f"pattern_matches: source '{source}' names service '{service}', "
            f"which service_contracts does not declare",
        )
    elif method not in declared[service]:
        report.warning(
            "unknown_reference",
            f"pattern_matches: source '{source}' names '{method}', "
            f"which {service} does not declare",
        )


def _known_pattern_ids(report):
    """Every pattern id that may legitimately appear, or None when unreadable.

    The set comes from `kernel.pattern_catalog` — the same module the classifier
    reads — so it includes the three answers that are not catalogue patterns.
    Validating against the catalogue files alone flagged those deliberate answers
    as references to something that does not exist.

    None means "cannot tell", so an unreadable catalogue reports itself once
    rather than turning every match into an unknown reference.
    """
    try:
        return known_pattern_ids()
    except (OSError, ValueError) as error:
        report.error("malformed_document", f"pattern catalogue unreadable: {error}")
        return None


def _declared_methods(documents):
    """service -> the method names it declares, for resolving contract sources."""
    services = documents.get("service_contracts")
    if not isinstance(services, list):
        return {}
    declared = {}
    for service in services:
        if not isinstance(service, dict) or not service.get("service_name"):
            continue
        methods = service.get("methods")
        declared[service["service_name"]] = {
            method.get("name")
            for method in (methods if isinstance(methods, list) else [])
            if isinstance(method, dict) and method.get("name")
        }
    return declared
