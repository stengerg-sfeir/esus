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
        report.note(
            "missing_pattern",
            f"pattern_matches: {entry.get('text')!r} {reason} — no pattern covers it "
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
