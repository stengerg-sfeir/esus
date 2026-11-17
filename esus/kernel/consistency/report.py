"""Findings, severity levels and report rendering."""

from dataclasses import dataclass, field

ERROR = "error"
WARNING = "warning"

# A note is an observation the checker cannot call a defect: an empty
# intentions or invariants list is a correct extraction when the requirements
# state none, and the checker has no access to the requirements to tell the
# difference. Notes are reported but never counted, so "0 errors, 0 warnings"
# stays an accurate statement about a clean run.
NOTE = "note"

SEVERITY_ORDER = (ERROR, WARNING, NOTE)
SEVERITY_HEADERS = {ERROR: "❌ ERRORS", WARNING: "⚠️  WARNINGS", NOTE: "NOTES"}

MAX_SUBJECTS = 8
GRAND_TOTAL_RULES = 10

RULE_TITLES = {
    "missing_directory": "Output directory does not exist",
    "missing_document": "Document is missing",
    "malformed_document": "Document is not valid JSON",
    "unexpected_shape": "Document has an unexpected shape",
    "invalid_value": "Value has the wrong type or content",
    "invalid_identifier": "Name is empty",
    "placeholder_value": "Placeholder left by the extractor",
    "empty_section": "Section is empty",
    "duplicate_entry": "Duplicate entry",
    "unknown_reference": "Reference points at something that does not exist",
    "name_variant": "Reference spells a name differently from its definition",
    "class_name_entity": "Entity field holds a class name",
    "no_mapping": "Repository entity has no entity mapping",
    "no_repository": "CRUD entity has no repository",
    "missing_primary_key": "Model declares no primary key",
    "nullable_primary_key": "Primary key is marked nullable",
    "non_unique_primary_key": "Primary key is marked non-unique",
    "primary_key_mismatch": "Mapping primary key is not a field of the entity",
    "unsupported_value": "Value is outside the allowed set",
    "unresolved_adapter_target": "Adapter target services cannot be resolved",
    "inconsistent_adapter": "Adapter transform and lookup entity disagree",
    "inconsistent_interface": "One repository declared differently in two documents",
    "inconsistent_facade": "The facade declares a parser and an argument list that disagree",
    "missing_parameters": "Method promises arguments but declares none",
    "inconsistent_invariant": "Invariant contradicts the field it names",
    "unmet_crud_operation": "Claimed operation has no implementing method",
    "low_confidence": "Classification confidence is below the floor",
    "narrow_margin": "The top two answers were too close to call — the verdict may differ between runs",
    "corrected_claim": "An impossible pattern was claimed and a possible one recorded instead",
    "missing_pattern": "No pattern covers this requirement — a vocabulary gap",
    "unused_error": "A declared error type that no method raises",
    "contradictory_raise": "A method that creates a record claims it can fail to find one",
    "misplaced_field": "An adapter field mapped to a parameter that is not its own",
    "mismatched_transform": "A transform that does not fit the field it is applied to",
    "missing_command": "A command the requirements name that the surface does not declare",
    "missing_flag": "A flag the requirements pass that the surface does not declare",
    "unbacked_command": "A command the surface declares that no service method implements",
    "unreachable_error": "A not-found error no method raises, while its reader exists",
    "duplicate_error_subject": "Two error types name the same missing record",
}


@dataclass(frozen=True)
class Finding:
    """A single consistency problem, identified by its rule."""

    severity: str
    rule: str
    message: str

    def render(self):
        return f"[{self.rule}] {self.message}"


@dataclass
class Report:
    """Collects the findings for one output directory."""

    prompt_name: str
    findings: list = field(default_factory=list)
    _seen: set = field(default_factory=set, repr=False)

    def add(self, severity, rule, message):
        key = (severity, rule, message)
        if key in self._seen:
            return
        self._seen.add(key)
        self.findings.append(Finding(*key))

    def error(self, rule, message):
        self.add(ERROR, rule, message)

    def warning(self, rule, message):
        self.add(WARNING, rule, message)

    def note(self, rule, message):
        self.add(NOTE, rule, message)

    @property
    def sorted_findings(self):
        return sorted(
            self.findings,
            key=lambda finding: (
                SEVERITY_ORDER.index(finding.severity),
                finding.rule,
                finding.message,
            ),
        )

    def of_severity(self, severity):
        return [f for f in self.sorted_findings if f.severity == severity]

    @property
    def errors(self):
        return self.of_severity(ERROR)

    @property
    def warnings(self):
        return self.of_severity(WARNING)

    @property
    def notes(self):
        return self.of_severity(NOTE)

    @property
    def counts(self):
        """Errors and warnings only — a note is not a defect."""
        return len(self.errors), len(self.warnings)


def render_report(report, show_all=False):
    """Render one directory's report block."""
    lines = ["", "=" * 60, f"  CONSISTENCY REPORT: {report.prompt_name}", "=" * 60]

    if not report.findings:
        lines.append("  ✅ All checks passed — fully consistent.")
    else:
        for severity in SEVERITY_ORDER:
            findings = report.of_severity(severity)
            if not findings:
                continue
            lines.append("")
            lines.append(f"  {SEVERITY_HEADERS[severity]} ({len(findings)}):")
            shown = findings if show_all else findings[:MAX_SUBJECTS]
            lines.extend(f"     • {finding.render()}" for finding in shown)
            hidden = len(findings) - len(shown)
            if hidden:
                lines.append(f"     … and {hidden} more (--all-findings to list them)")

    errors, warnings = report.counts
    summary = f"\n  Summary: {errors} error(s), {warnings} warning(s)"
    if report.notes:
        summary += f", {len(report.notes)} note(s)"
    lines.append(summary)
    return "\n".join(lines)


def with_suggestions(message, suggestions):
    """Append a "did you mean" hint to a finding message when one is available."""
    if not suggestions:
        return message
    return f"{message} (did you mean: {', '.join(suggestions)}?)"


def render_grand_total(reports):
    """Render the cross-directory tally, including the noisiest rules."""
    total_errors = sum(report.counts[0] for report in reports)
    total_warnings = sum(report.counts[1] for report in reports)
    total_notes = sum(len(report.notes) for report in reports)

    header = f"  GRAND TOTAL: {total_errors} error(s), {total_warnings} warning(s)"
    if total_notes:
        header += f", {total_notes} note(s)"
    lines = [
        "",
        "=" * 60,
        f"{header} across {len(reports)} prompt(s)",
        "=" * 60,
    ]

    tally = {}
    for report in reports:
        for finding in report.findings:
            key = (finding.severity, finding.rule)
            tally[key] = tally.get(key, 0) + 1

    if tally:
        lines.append("")
        lines.append("  By rule:")
        ranked = sorted(tally.items(), key=lambda item: (-item[1], item[0]))
        for (severity, rule), count in ranked[:GRAND_TOTAL_RULES]:
            lines.append(f"     {count:>4}  [{severity}] {rule} — {RULE_TITLES.get(rule, rule)}")
        if len(ranked) > GRAND_TOTAL_RULES:
            lines.append(f"     … and {len(ranked) - GRAND_TOTAL_RULES} more rule(s)")

    lines.append("")
    return "\n".join(lines)
