"""Classify oracle outcomes into code findings, case defects and gaps."""

from __future__ import annotations

import re


def _field_scope(reason, source):
    """Whether an undeclared field is named by the prompt or only assumed."""
    text = str(reason or "")
    match = re.search(r"(?:field|state field) ['\"]?([A-Za-z0-9_.]+)", text)
    if not match:
        return "under_specified"
    field = match.group(1).partition(".")[2] or match.group(1)
    words = re.findall(r"[a-z0-9]+", str(source or "").lower())
    compact = "".join(words)
    token = re.sub(r"[^a-z0-9]", "", field.lower())
    named = token in compact
    if not named and token.endswith("s"):
        named = token[:-1] in compact
    return "coverage_gap: schema" if named else "under_specified"


def classify(status, reason, source=None):
    text = str(reason or "").lower()
    requirement = str(source or "").lower()
    if status == "passed":
        return "passed"
    if status == "under_specified":
        return "under_specified"
    if status == "case_defect":
        return "case_defect: setup"
    if status == "unbound":
        if ("cannot resolve given entity" in text
                and any(word in requirement for word in
                        ("calculator", "command line", "cli", "program"))):
            return "under_specified"
        if "create case expects" in text:
            return _field_scope(reason, source)
        if ("expected state field" in text
                or "supplies no value for required field" in text):
            return _field_scope(reason, source)
        if "ambiguous action binding" in text:
            return "coverage_gap: ambiguous action"
        if "has no sort parameter" in text:
            return "coverage_gap: method signature"
        if "seeded data matches its filter" in text:
            return "case_defect: setup"
        if "represented by join model" in text:
            return "under_specified"
        if "unknown expected entity" in text:
            return "coverage_gap: schema"
        if ("expected state" in text
                or "primary-key" in text
                or "cannot resolve given entity" in text
                or "is not an entity named" in text
                or "is not a mapping" in text
                or "setup needs" in text):
            return "case_defect: setup"
        if "no generated method" in text or "no generated cli path" in text:
            return "coverage_gap: missing action"
        if any(marker in text for marker in (
                "supplies no new value", "supplies no value for required field",
                "passes parameter name", "list case expects fewer rows",
                "supplies unknown argument")):
            return "case_defect: setup"
        return "coverage_gap: other"
    if status != "failed":
        return f"{status}: other"
    if "unknown expected entity" in text:
        return "coverage_gap: schema"
    if "has no sort parameter" in text:
        return "coverage_gap: method signature"
    if "seeded data matches its filter" in text:
        return "case_defect: setup"
    if "has no attribute 'get'" in text and ("'str' object" in text
                                              or "str object" in text):
        # The case supplied a bare payload field name where the generated
        # method expects a structured payload; the prompt did not determine
        # that payload shape.
        return "under_specified"
    if "soft delete" in requirement and (
            "state value" in text or "is " in text and "expected " in text):
        return "case_defect: soft-delete expectation"
    if ("expected str, bytes or os.pathlike" in text
            or "no such file or directory" in text):
        return "case_defect: missing file fixture"
    if ("cannot read" in text
            and "soft delete" in requirement
            and any(word in requirement for word in
                    ("remains in the database", "still exists", "not removed"))):
        return "behavior: soft delete"
    if ("is datetime.datetime" in text and "expected '" in text) \
            or "datatype mismatch" in text \
            or (".id is " in text and "expected 1" in text):
        return "case_defect: setup"
    if "positional argument but" in text or "unexpected keyword" in text:
        return "coverage_gap: method signature"
    if any(word in text for word in (
            "matched 0 records", "matched no records", "notfounderror",
            "not found", "already exists", "unknown scenario reference",
            "keyerror", "takes from", "unexpected keyword",
            "integrityerror", "not null constraint")):
        return "case_defect: setup"
    if "row count is" in text and "expected -" in text:
        return "case_defect: invalid row expectation"
    if "is none, expected '" in text and "status" in text:
        expected = text.split("expected '", 1)[-1].split("'", 1)[0]
        if expected and expected not in requirement:
            return "case_defect: unstated status expectation"
    if "row count is" in text:
        return "behavior: row count"
    if "is " in text and ", expected " in text:
        target = text.split(" is ", 1)[0].strip()
        field = target.rpartition(".")[2] or target
        tokens = [field] + [part for part in field.split("_") if len(part) > 3]
        named = any(re.search(r"(?<![a-z0-9])" + re.escape(token) +
                              r"(?![a-z0-9])", requirement)
                    for token in tokens)
        if not named:
            return "under_specified"
        return "behavior: state value"
    if "expected" in text and "no error was raised" in text:
        return "behavior: expected error missing"
    if text.startswith("raised ") and "expected" in text:
        return "behavior: wrong error"
    return "behavior: other"
