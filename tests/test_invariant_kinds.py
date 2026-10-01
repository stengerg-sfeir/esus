"""Step C's rule/schema tag, and the filter it drives at step F.

Step C classifies an invariant the way it writes it — `rule` when the statement
constrains behaviour and may map onto a kernel pattern, `schema` when it only
restates a single field's type, nullability, uniqueness, key or allowed values.
The value is closed by the grammar, so the distinction is one the extractor
cannot get wrong silently, and step F classifies the rules only.

Why the filter exists, measured across the seven prompts: of 75 invariants,
most are `schema` statements, and their classification is noise. Worse than
noise — most of that noise scored *above* the 0.2 confidence floor
(`budget.month is 'YYYY-MM' string` matched `BUDGET_OVERFLOW_GUARD` at 0.58,
`created_at and updated_at ... valid timestamps` matched `STATE_TRANSITION_GUARD`
at 0.73), so it was never even reported. Only a minority are behavioural:
`wine.selling_price must be strictly greater than wine.cost_price` (0.62) and
`loan.return_date must be null if loan.status is 'active'` (0.84) are real
matches worth keeping.
"""

import unittest

from kernel.extraction.classification import classification_items
from kernel.extraction.prompts import INVARIANTS_SYSTEM


def tagged(*pairs):
    """Invariants as step C writes them: a (text, kind) pair per entry."""
    return [{"text": text, "kind": kind} for text, kind in pairs]


class StepFClassifiesRulesOnly(unittest.TestCase):
    """The filter, which is the point of the tag."""

    def items(self, invariants):
        documents = {"invariants": invariants, "service_contracts": []}
        return classification_items(documents)

    def test_a_schema_invariant_is_not_classified(self):
        items = self.items(tagged(("member.is_active must be a boolean", "schema")))
        self.assertEqual(items, [])

    def test_a_rule_invariant_is_classified(self):
        items = self.items(tagged(("available_copies must not exceed the copies added", "rule")))
        self.assertEqual(items, [("invariant", "available_copies must not exceed the copies added")])

    def test_only_the_rules_survive_a_mixed_list(self):
        items = self.items(
            tagged(
                ("category.description is optional", "schema"),
                ("loan.return_date must be null if loan.status is 'active'", "rule"),
                ("category.id is auto-incremented primary key", "schema"),
                ("wine.selling_price must be strictly greater than wine.cost_price", "rule"),
            )
        )
        self.assertEqual(
            [text for _, text in items],
            [
                "loan.return_date must be null if loan.status is 'active'",
                "wine.selling_price must be strictly greater than wine.cost_price",
            ],
        )

    def test_contract_methods_are_unaffected_by_the_tag(self):
        documents = {
            "invariants": tagged(("member.is_active must be a boolean", "schema")),
            "service_contracts": [
                {"service_name": "LoanService", "methods": [{"name": "borrow_book",
                                                             "description": "Borrows one."}]}
            ],
        }
        self.assertEqual(
            classification_items(documents),
            [("contract:LoanService.borrow_book", "borrow_book: Borrows one.")],
        )

    def test_an_untagged_string_is_still_classified(self):
        """The pre-tagging shape: every invariant was classified then."""
        items = self.items(["sku must be unique across all products"])
        self.assertEqual(items, [("invariant", "sku must be unique across all products")])

    def test_an_empty_or_missing_document_yields_nothing(self):
        for value in ([], None, {"invariants": []}):
            with self.subTest(value=value):
                documents = value if isinstance(value, dict) else {"invariants": value,
                                                                  "service_contracts": []}
                self.assertEqual(classification_items(documents), [])

    def test_a_schema_only_document_classifies_nothing(self):
        """The whole reason for the filter: no operation, so no answer is right."""
        items = self.items(
            tagged(
                ("category.description is optional", "schema"),
                ("product.low_active is optional and defaults to False", "schema"),
                ("member.membership_date must be a valid date", "schema"),
            )
        )
        self.assertEqual(items, [])


class ThePromptAsksForBothKinds(unittest.TestCase):
    """The prompt must name both kinds, or the grammar's two literals are unprompted."""

    def test_the_prompt_defines_rule_and_schema(self):
        self.assertIn("'schema'", INVARIANTS_SYSTEM)
        self.assertIn("'rule'", INVARIANTS_SYSTEM)

    def test_the_prompt_gives_the_tagged_output_shape(self):
        self.assertIn('"kind"', INVARIANTS_SYSTEM)
        self.assertIn('"text"', INVARIANTS_SYSTEM)


if __name__ == "__main__":
    unittest.main(verbosity=2)
