"""The runner-up, the margin, and the two categories a match can be in.

Why this exists: the winner alone cannot say whether a match was decided. The
same kind of requirement (`read_all_*`) landed on a gap in one prompt and on
`FILTER_WITH_PAGINATION` in another because the two options were near-tied and
only the winner was written down.

Three things are pinned here:

- the runner-up is the best answer **other than the one recorded** — it may
  never be the recorded pattern itself, which is what let three notes read
  `'FILTER_BY_FIELD' ... over 'FILTER_BY_FIELD'`;
- both stages are judged, and the **domain** first, because step 1 decides which
  pattern list step 2 even saw;
- a match carries one explicit `decision` — `decided`, `undecided`, `undefined`
  — instead of a threshold for the reader to re-derive.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.consistency import checks_patterns  # noqa: E402
from kernel.consistency.report import NOTE, Report  # noqa: E402
from kernel.extraction import classification  # noqa: E402


def result(pattern_id, step2, step1=None, domain="REPO_QUERY", confidence=None):
    """A classifier result shaped like `classify_requirement_2step`'s return."""
    return {
        "domain": domain,
        "pattern_id": pattern_id,
        "confidence": confidence if confidence is not None else max(step2.values(), default=0.0),
        "step1_probabilities": step1 if step1 is not None else {domain: 1.0},
        "step2_probabilities": step2,
    }


class RunnerUpTests(unittest.TestCase):
    def test_the_second_best_answer_is_returned(self):
        probabilities = {"READ_ALL": 0.70, "FILTER_BY_FIELD": 0.64, "THRESHOLD_SCAN": 0.02}
        pattern_id, confidence = classification._runner_up(
            result("READ_ALL", probabilities), "READ_ALL"
        )
        self.assertEqual(pattern_id, "FILTER_BY_FIELD")
        self.assertAlmostEqual(confidence, 0.64)

    def test_the_runner_up_is_never_the_recorded_pattern(self):
        """**The D1 regression.**

        The model claimed `AGGREGATE_BY_FK` (0.44) and the shape rule corrected it
        to `FILTER_BY_FIELD` (0.30). Excluding the *claim* left the corrected
        pattern free to be its own runner-up, and three corpus notes compared a
        pattern with itself because of it. Excluding the *recorded* pattern
        cannot.
        """
        probabilities = {
            "AGGREGATE_BY_FK": 0.44,
            "FILTER_BY_FIELD": 0.30,
            "READ_ALL": 0.10,
        }
        pattern_id, _ = classification._runner_up(
            result("AGGREGATE_BY_FK", probabilities), "FILTER_BY_FIELD"
        )
        self.assertNotEqual(
            pattern_id, "FILTER_BY_FIELD", "the runner-up must not be the recorded answer"
        )
        self.assertEqual(pattern_id, "AGGREGATE_BY_FK")

    def test_a_recorded_pattern_absent_from_the_distribution_still_has_a_runner_up(self):
        """The domain may have short-circuited, leaving step 2 empty."""
        pattern_id, confidence = classification._runner_up(
            result("STANDARD_CRUD", {}), "STANDARD_CRUD"
        )
        self.assertEqual((pattern_id, confidence), (None, 0.0))

    def test_a_single_candidate_has_no_runner_up(self):
        pattern_id, _ = classification._runner_up(
            result("READ_ALL", {"READ_ALL": 0.9}), "READ_ALL"
        )
        self.assertIsNone(pattern_id)

    def test_the_runner_up_is_scaled_like_the_confidence(self):
        """Otherwise the margin compares two different quantities.

        `confidence` is domain x pattern; the runner-up must be scaled by the
        same domain probability. Before this, the margin came out negative on
        inventory's first invariant, which no real top-two gap can be.
        """
        probabilities = {"READ_ALL": 0.6, "FILTER_BY_FIELD": 0.5}
        pattern_id, confidence = classification._runner_up(
            result(
                "READ_ALL",
                probabilities,
                step1={"REPO_QUERY": 0.8, "SERVICE_GUARD": 0.2},
                confidence=0.48,
            ),
            "READ_ALL",
        )
        self.assertEqual(pattern_id, "FILTER_BY_FIELD")
        self.assertAlmostEqual(confidence, 0.8 * 0.5)

    def test_missing_probabilities_yield_no_runner_up(self):
        pattern_id, _ = classification._runner_up(
            {"pattern_id": "READ_ALL"}, "READ_ALL"
        )
        self.assertIsNone(pattern_id)


class DomainRunnerUpTests(unittest.TestCase):
    """Step 1's own runner-up, which nothing recorded before."""

    def test_the_second_best_domain_is_returned(self):
        step1 = {"REPO_QUERY": 0.36, "STANDARD_CRUD": 0.33, "NO_MATCH": 0.31}
        domain, confidence = classification._domain_runner_up(
            result("READ_ALL", {"READ_ALL": 1.0}, step1=step1)
        )
        self.assertEqual(domain, "STANDARD_CRUD")
        self.assertAlmostEqual(confidence, 0.33)

    def test_a_single_domain_has_no_runner_up(self):
        domain, confidence = classification._domain_runner_up(
            result("READ_ALL", {"READ_ALL": 1.0}, step1={"REPO_QUERY": 1.0})
        )
        self.assertEqual((domain, confidence), (None, 0.0))

    def test_no_distribution_yields_no_runner_up(self):
        domain, _ = classification._domain_runner_up({"pattern_id": "READ_ALL"})
        self.assertIsNone(domain)


class DecideTests(unittest.TestCase):
    """The three categories, in one function."""

    def test_a_gap_is_undefined_whatever_the_margins_say(self):
        """A gap must not be routed as a choice between two patterns."""
        decision, stage = classification._decide("NO_PATTERN_IN_DOMAIN", 0.9, 0.9)
        self.assertEqual((decision, stage), (classification.UNDEFINED, None))

    def test_a_near_tied_domain_is_undecided_at_the_domain_stage(self):
        """Even when the pattern margin is wide: the wrong list was compared."""
        decision, stage = classification._decide("READ_ALL", 0.9, 0.01)
        self.assertEqual(decision, classification.UNDECIDED)
        self.assertEqual(stage, classification.STAGE_DOMAIN)

    def test_a_near_tied_pattern_is_undecided_at_the_pattern_stage(self):
        decision, stage = classification._decide("READ_ALL", 0.01, 0.9)
        self.assertEqual(decision, classification.UNDECIDED)
        self.assertEqual(stage, classification.STAGE_PATTERN)

    def test_the_domain_stage_wins_when_both_are_near_tied(self):
        """It decides whether step 2's candidates were the right list at all."""
        _, stage = classification._decide("READ_ALL", 0.01, 0.01)
        self.assertEqual(stage, classification.STAGE_DOMAIN)

    def test_a_wide_margin_both_stages_is_decided(self):
        decision, stage = classification._decide("READ_ALL", 0.9, 0.9)
        self.assertEqual((decision, stage), (classification.DECIDED, None))

    def test_no_alternative_is_decided_not_undecided(self):
        """**The crash**: `margin=None` is not a near-tie.

        A `None` margin means nothing was there to compare against, and the plain
        `<` this replaced raised `TypeError: '<' not supported between instances
        of 'NoneType' and 'float'` on the first real run. The suite passed,
        because every case here had passed a number.
        """
        decision, stage = classification._decide("READ_ALL", None, 0.9)
        self.assertEqual((decision, stage), (classification.DECIDED, None))

    def test_no_alternative_still_reports_a_near_tied_domain(self):
        decision, stage = classification._decide("READ_ALL", None, 0.01)
        self.assertEqual(decision, classification.UNDECIDED)
        self.assertEqual(stage, classification.STAGE_DOMAIN)


class MarginNoteTests(unittest.TestCase):
    def report_for(self, entry):
        report = Report("test")
        checks_patterns._check_margin(entry, report)
        return report

    # --- the guard ---

    def test_a_self_comparing_margin_is_an_error(self):
        """**The D1 guard**: this shape must never be reported as a signal."""
        report = self.report_for(
            {
                "pattern_id": "FILTER_BY_FIELD",
                "text": "read_budgets_by_category: Reads all budgets for a category",
                "margin": 0.14,
                "runner_up_pattern_id": "FILTER_BY_FIELD",
            }
        )
        self.assertEqual(len(report.errors), 1)
        self.assertEqual(report.errors[0].rule, "invalid_value")
        self.assertIn("with itself", report.errors[0].message)

    def test_an_unknown_decision_is_an_error(self):
        report = self.report_for(
            {"pattern_id": "READ_ALL", "text": "x", "decision": "maybe"}
        )
        self.assertEqual(len(report.errors), 1)
        self.assertEqual(report.errors[0].rule, "unsupported_value")

    # --- the two categories ---

    def test_an_undecided_pattern_is_reported_with_its_alternative(self):
        report = self.report_for(
            {
                "pattern_id": "FILTER_WITH_PAGINATION",
                "text": "read_all_categories: Returns all categories in the database",
                "decision": "undecided",
                "undecided_stage": "pattern",
                "margin": 0.02,
                "runner_up_pattern_id": "READ_ALL",
            }
        )
        self.assertEqual(len(report.notes), 1)
        self.assertEqual(report.notes[0].severity, NOTE)
        self.assertEqual(report.notes[0].rule, "narrow_margin")
        self.assertIn("READ_ALL", report.notes[0].message)

    def test_an_undecided_domain_names_the_domain_alternative(self):
        report = self.report_for(
            {
                "pattern_id": "READ_ALL",
                "text": "read_all_categories: Returns all categories",
                "decision": "undecided",
                "undecided_stage": "domain",
                "domain": "REPO_QUERY",
                "domain_runner_up": "STANDARD_CRUD",
                "domain_margin": 0.01,
                "margin": 0.70,
                "runner_up_pattern_id": "FILTER_BY_FIELD",
            }
        )
        self.assertEqual(len(report.notes), 1)
        self.assertIn("STANDARD_CRUD", report.notes[0].message)
        self.assertIn("domains", report.notes[0].message)

    def test_a_decided_answer_is_silent(self):
        report = self.report_for(
            {
                "pattern_id": "READ_ALL",
                "text": "read_all_categories: Reads all categories from the database.",
                "decision": "decided",
                "margin": 0.71,
                "runner_up_pattern_id": "FILTER_BY_FIELD",
                "domain_margin": 0.9,
                "domain_runner_up": "NO_MATCH",
            }
        )
        self.assertEqual(report.notes, [])

    def test_an_undefined_answer_is_not_reported_twice(self):
        """`_report_gaps` already reports this entry; the margin must not repeat it."""
        report = self.report_for(
            {
                "pattern_id": "NO_PATTERN_IN_DOMAIN",
                "text": "read_all_books: Reads all Book entities from the database.",
                "decision": "undefined",
                "margin": None,
                "runner_up_pattern_id": None,
                "runner_up_confidence": 0.0,
            }
        )
        self.assertEqual(report.notes, [])
        self.assertEqual(report.errors, [])

    # --- a document written before the field existed ---

    def test_a_document_without_the_decision_still_reports_from_the_margin(self):
        report = self.report_for(
            {
                "pattern_id": "FILTER_WITH_PAGINATION",
                "text": "read_all_categories: Returns all categories",
                "margin": 0.02,
                "runner_up_pattern_id": "READ_ALL",
            }
        )
        self.assertEqual(len(report.notes), 1)
        self.assertIn("READ_ALL", report.notes[0].message)

    def test_a_document_without_the_decision_reports_the_domain_tie_first(self):
        report = self.report_for(
            {
                "pattern_id": "READ_ALL",
                "text": "read_all_categories: Returns all categories",
                "margin": 0.70,
                "runner_up_pattern_id": "FILTER_BY_FIELD",
                "domain_margin": 0.01,
                "domain_runner_up": "STANDARD_CRUD",
            }
        )
        self.assertEqual(len(report.notes), 1)
        self.assertIn("STANDARD_CRUD", report.notes[0].message)

    def test_a_document_without_the_field_is_silent_when_decisive(self):
        report = self.report_for({"pattern_id": "READ_ALL", "text": "old document"})
        self.assertEqual(report.notes, [])

    def test_a_short_circuited_answer_is_silent(self):
        report = self.report_for(
            {
                "pattern_id": "STANDARD_CRUD",
                "text": "get_category_by_id: Reads one category by its ID",
                "runner_up_pattern_id": None,
                "runner_up_confidence": 0.0,
                "margin": 0.0,
            }
        )
        self.assertEqual(report.notes, [])


class RecordedConfidenceTests(unittest.TestCase):
    """`confidence` must describe the pattern actually recorded.

    Keeping the classifier's figure for the *claim* beside a corrected pattern is
    what made `margin` cancel to 0.0 on every corrected entry — measured on ten
    of ten — and so report each one as a near-tie.
    """

    def test_a_normal_match_keeps_the_classifier_figure(self):
        probabilities = {"READ_ALL": 0.7, "FILTER_BY_FIELD": 0.2}
        confidence = classification._recorded_confidence(
            result("READ_ALL", probabilities, confidence=0.63), "READ_ALL"
        )
        self.assertAlmostEqual(confidence, 0.7)

    def test_a_corrected_match_reports_the_recorded_pattern_not_the_claim(self):
        """FILTER_BY_FIELD, corrected from AGGREGATE_BY_FK, must report its own 0.30."""
        probabilities = {"AGGREGATE_BY_FK": 0.44, "FILTER_BY_FIELD": 0.30}
        confidence = classification._recorded_confidence(
            result("AGGREGATE_BY_FK", probabilities, confidence=0.44), "FILTER_BY_FIELD"
        )
        self.assertAlmostEqual(confidence, 0.30)

    def test_a_domain_short_circuit_has_no_second_stage_to_recompute_from(self):
        confidence = classification._recorded_confidence(
            result("STANDARD_CRUD", {}, confidence=0.81), "STANDARD_CRUD"
        )
        self.assertAlmostEqual(confidence, 0.81)

    def test_the_domain_probability_scales_the_recorded_pattern(self):
        confidence = classification._recorded_confidence(
            result(
                "READ_ALL",
                {"READ_ALL": 0.5},
                step1={"REPO_QUERY": 0.8, "NO_MATCH": 0.2},
                confidence=0.4,
            ),
            "READ_ALL",
        )
        self.assertAlmostEqual(confidence, 0.8 * 0.5)


class ViablePatternTests(unittest.TestCase):
    """The margin is a question about the *choice*, so it excludes impossibles."""

    def test_a_records_return_leaves_only_collection_patterns(self):
        candidates = {"AGGREGATE_BY_FK": 0.44, "FILTER_BY_FIELD": 0.30, "READ_ALL": 0.10}
        viable = classification._viable_patterns(
            result("AGGREGATE_BY_FK", candidates), "List[Expense]"
        )
        self.assertNotIn("AGGREGATE_BY_FK", viable)
        self.assertIn("FILTER_BY_FIELD", viable)
        self.assertIn("READ_ALL", viable)

    def test_a_gap_sentinel_is_never_viable(self):
        candidates = {"FILTER_BY_FIELD": 0.5, "NO_PATTERN_IN_DOMAIN": 0.4}
        viable = classification._viable_patterns(
            result("FILTER_BY_FIELD", candidates), "List[Expense]"
        )
        self.assertNotIn("NO_PATTERN_IN_DOMAIN", viable)

    def test_an_unknown_return_type_leaves_every_candidate_in(self):
        """An invariant carries no signature, so nothing can be excluded."""
        self.assertIsNone(
            classification._viable_patterns(result("READ_ALL", {"READ_ALL": 1.0}), None)
        )

    def test_the_corrected_margin_is_measured_among_viable_answers(self):
        """**The ten-of-ten defect**: this margin used to come out 0.0."""
        candidates = {"AGGREGATE_BY_FK": 0.44, "FILTER_BY_FIELD": 0.30, "READ_ALL": 0.10}
        raw = result("AGGREGATE_BY_FK", candidates, confidence=0.44)
        viable = classification._viable_patterns(raw, "List[Expense]")
        runner_up, runner_up_confidence = classification._runner_up(
            raw, "FILTER_BY_FIELD", viable
        )
        confidence = classification._recorded_confidence(raw, "FILTER_BY_FIELD")
        self.assertEqual(runner_up, "READ_ALL")
        self.assertNotAlmostEqual(confidence - runner_up_confidence, 0.0)
        self.assertAlmostEqual(confidence - runner_up_confidence, 0.30 - 0.10)


class GapMarginTests(unittest.TestCase):
    """A gap is not a choice, so it has no margin — and must not carry one.

    Six of the seven gaps came out with a large *negative* margin before this
    (`-0.48`), because the figure compared the entry's own sentinel probability
    against the claim's. A number there is a defect, not a signal.
    """

    def report_for(self, entry):
        report = Report("test")
        checks_patterns._check_margin(entry, report)
        return report

    def test_an_empty_viable_set_is_not_none(self):
        """Empty says "nothing can be right" — the gap — which None does not."""
        candidates = {"AGGREGATE_BY_FK": 0.5, "COUNT_ACTIVE_BY_FK": 0.3}
        viable = classification._viable_patterns(
            result("AGGREGATE_BY_FK", candidates), "Loan | None"
        )
        self.assertIsNotNone(viable)
        self.assertEqual(viable, set())

    def test_no_viable_candidate_leaves_no_runner_up(self):
        """With nothing viable there is nothing to compare against."""
        candidates = {"AGGREGATE_BY_FK": 0.5, "COUNT_ACTIVE_BY_FK": 0.3}
        runner_up, confidence = classification._runner_up(
            result("AGGREGATE_BY_FK", candidates), "NO_PATTERN_IN_DOMAIN", set()
        )
        self.assertEqual((runner_up, confidence), (None, 0.0))

    def test_a_gap_with_a_margin_is_an_error(self):
        report = self.report_for(
            {
                "pattern_id": "NO_PATTERN_IN_DOMAIN",
                "text": "borrow_book(member_id: int, book_id: int) -> Loan | None: Borrow a book.",
                "decision": "undefined",
                "margin": -0.4787,
                "runner_up_pattern_id": "READ_ALL",
                "claimed_pattern_id": "READ_ALL",
                "rejection": "READ_ALL returns collection, but this method returns entity",
            }
        )
        self.assertEqual(len(report.errors), 1)
        self.assertEqual(report.errors[0].rule, "invalid_value")
        self.assertIn("not a choice", report.errors[0].message)

    def test_a_gap_without_a_margin_is_accepted(self):
        report = self.report_for(
            {
                "pattern_id": "NO_PATTERN_IN_DOMAIN",
                "text": "borrow_book(member_id: int, book_id: int) -> Loan | None: Borrow a book.",
                "decision": "undefined",
                "margin": None,
                "runner_up_pattern_id": None,
                "runner_up_confidence": 0.0,
                "claimed_pattern_id": "READ_ALL",
                "rejection": "READ_ALL returns collection, but this method returns entity",
            }
        )
        self.assertEqual(report.errors, [])
        self.assertEqual(report.notes, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
