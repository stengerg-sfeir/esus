"""Classify oracle outcomes into code findings, case defects and gaps."""

from __future__ import annotations


def classify(status, reason, source=None):
    text = str(reason or "").lower()
    requirement = str(source or "").lower()
    if status == "passed":
        return "passed"
    if status == "unbound":
        if "ambiguous action binding" in text:
            return "coverage_gap: ambiguous action"
        if ("expected state" in text
                or "primary-key" in text
                or "cannot resolve given entity" in text
                or "is not an entity named" in text
                or "is not a mapping" in text
                or "setup needs" in text):
            return "case_defect: setup"
        if "no generated method" in text or "no generated cli path" in text:
            return "coverage_gap: missing action"
        return "coverage_gap: other"
    if status != "failed":
        return f"{status}: other"
    if ("cannot read" in text
            and "soft delete" in requirement
            and any(word in requirement for word in
                    ("remains in the database", "still exists", "not removed"))):
        return "behavior: soft delete"
    if any(word in text for word in (
            "matched 0 records", "matched no records", "notfounderror",
            "not found", "already exists", "unknown scenario reference",
            "keyerror", "takes from", "unexpected keyword",
            "integrityerror", "not null constraint")):
        return "case_defect: setup"
    if "row count is" in text:
        return "behavior: row count"
    if "is " in text and ", expected " in text:
        return "behavior: state value"
    if "expected" in text and "no error was raised" in text:
        return "behavior: expected error missing"
    if text.startswith("raised ") and "expected" in text:
        return "behavior: wrong error"
    return "behavior: other"
