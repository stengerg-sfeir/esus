"""The two contradictions removed by `kernel.extraction.repairs`.

Each test pins one decision and, where the repair must stay silent, pins that
silence too — a repair that removes a value the document does not contradict is
worse than no repair. The predicates are shared with the checker, so these also
assert that the repair agrees with the rule that used to report the defect.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import repairs  # noqa: E402


class Log:
    def __init__(self):
        self.lines = []

    def write(self, text):
        self.lines.append(text)


def contract(name, raises):
    return {"service_name": "S", "methods": [{"name": name, "raises": list(raises)}]}


class DuplicateErrorSubjectTests(unittest.TestCase):
    def test_two_names_for_one_missing_record_leave_one(self):
        errors = [{"name": "ProductNotFoundError"}, {"name": "MissingProductError"}]
        log = Log()
        kept, _ = repairs.repair_errors(errors, [], log)
        self.assertEqual([item["name"] for item in kept], ["ProductNotFoundError"])

    def test_the_kept_name_is_the_one_a_method_raises(self):
        errors = [{"name": "MissingProductError"}, {"name": "ProductNotFoundError"}]
        services = [contract("get_product_by_id", ["ProductNotFoundError"])]
        kept, _ = repairs.repair_errors(errors, services, Log())
        self.assertEqual([item["name"] for item in kept], ["ProductNotFoundError"])

    def test_a_reference_to_the_dropped_name_is_redirected(self):
        """Both names raised by different methods: the later one is redirected."""
        errors = [{"name": "ProductNotFoundError"}, {"name": "MissingProductError"}]
        services = [
            contract("get_product_by_id", ["ProductNotFoundError"]),
            contract("read_product_by_code", ["MissingProductError"]),
        ]
        _, repaired = repairs.repair_errors(errors, services, Log())
        self.assertEqual(
            repaired[1]["methods"][0]["raises"], ["ProductNotFoundError"]
        )

    def test_one_name_per_subject_is_left_alone(self):
        errors = [{"name": "ProductNotFoundError"}, {"name": "CategoryNotFoundError"}]
        log = Log()
        kept, _ = repairs.repair_errors(errors, [], log)
        self.assertEqual(len(kept), 2)
        self.assertEqual(log.lines, [])


class ContradictoryRaiseTests(unittest.TestCase):
    def test_a_create_loses_the_not_found_of_what_it_creates(self):
        services = [contract("create_product", ["ProductNotFoundError"])]
        _, repaired = repairs.repair_errors([], services, Log())
        self.assertEqual(repaired[0]["methods"][0]["raises"], [])

    def test_add_stock_keeps_the_product_not_found_it_must_find(self):
        """`add` is ambiguous: adding stock finds the product, so the raise stays."""
        services = [contract("add_stock", ["ProductNotFoundError"])]
        _, repaired = repairs.repair_errors([], services, Log())
        self.assertEqual(repaired[0]["methods"][0]["raises"], ["ProductNotFoundError"])

    def test_a_reader_keeps_its_not_found(self):
        services = [contract("read_product_by_id", ["ProductNotFoundError"])]
        _, repaired = repairs.repair_errors([], services, Log())
        self.assertEqual(repaired[0]["methods"][0]["raises"], ["ProductNotFoundError"])


class MismatchedTransformTests(unittest.TestCase):
    def adapter(self, field_name, transform):
        return {
            "action_name": "add_book",
            "input_fields": [{"field_name": field_name, "transform": transform}],
        }

    def test_a_count_converted_to_cents_becomes_direct(self):
        adapters = [self.adapter("copies", "DECIMAL_TO_CENTS")]
        repairs.repair_adapter_transforms(adapters, Log())
        self.assertEqual(adapters[0]["input_fields"][0]["transform"], "DIRECT")

    def test_a_money_amount_keeps_its_transform(self):
        adapters = [self.adapter("price_cents", "DECIMAL_TO_CENTS")]
        repairs.repair_adapter_transforms(adapters, Log())
        self.assertEqual(adapters[0]["input_fields"][0]["transform"], "DECIMAL_TO_CENTS")

    def test_a_single_name_read_as_a_list_becomes_direct(self):
        adapters = [self.adapter("title", "CSV_LIST")]
        repairs.repair_adapter_transforms(adapters, Log())
        self.assertEqual(adapters[0]["input_fields"][0]["transform"], "DIRECT")

    def test_a_date_field_keeps_its_transform(self):
        adapters = [self.adapter("expense_date", "ISO_DATE")]
        repairs.repair_adapter_transforms(adapters, Log())
        self.assertEqual(adapters[0]["input_fields"][0]["transform"], "ISO_DATE")

    def test_direct_is_never_touched(self):
        adapters = [self.adapter("anything", "DIRECT")]
        repairs.repair_adapter_transforms(adapters, Log())
        self.assertEqual(adapters[0]["input_fields"][0]["transform"], "DIRECT")


class UnraisedErrorTests(unittest.TestCase):
    """An error no method raises is dropped only when the requirements disown it."""

    REQUIREMENTS = (
        "Book lending CLI. Handles overdue loans and reports an overdue list."
    )

    def test_a_raised_error_is_kept(self):
        errors = [{"name": "BookNotFoundError"}]
        services = [contract("find_book", ["BookNotFoundError"])]
        kept = repairs.repair_unraised_errors(errors, services, self.REQUIREMENTS, Log())
        self.assertEqual([item["name"] for item in kept], ["BookNotFoundError"])

    def test_a_grounded_unraised_error_is_kept(self):
        """`OverdueLoanFoundError` is unraised but the requirements say 'overdue'."""
        errors = [{"name": "OverdueLoanFoundError"}]
        log = Log()
        kept = repairs.repair_unraised_errors(errors, [], self.REQUIREMENTS, log)
        self.assertEqual([item["name"] for item in kept], ["OverdueLoanFoundError"])
        self.assertEqual(log.lines, [])

    def test_a_named_unraised_error_is_kept(self):
        errors = [{"name": "BookNotFoundError"}]
        kept = repairs.repair_unraised_errors(
            errors, [], "raise BookNotFoundError when absent", Log()
        )
        self.assertEqual([item["name"] for item in kept], ["BookNotFoundError"])

    def test_an_ungrounded_validation_error_is_dropped(self):
        errors = [{"name": "InvalidInputError"}]
        log = Log()
        kept = repairs.repair_unraised_errors(errors, [], self.REQUIREMENTS, log)
        self.assertEqual(kept, [])
        self.assertEqual(len(log.lines), 1)

    def test_a_partly_grounded_validation_error_is_still_dropped(self):
        """'budget' grounds the name, but a validation shape is dropped anyway."""
        errors = [{"name": "InvalidBudgetAmountError"}]
        kept = repairs.repair_unraised_errors(errors, [], "the budget is stored", Log())
        self.assertEqual(kept, [])

    def test_an_ungrounded_unraised_error_is_dropped(self):
        errors = [{"name": "MalformedCSVError"}]
        kept = repairs.repair_unraised_errors(errors, [], "a book lending tool", Log())
        self.assertEqual(kept, [])

    def test_a_grounded_validation_error_is_kept(self):
        """cli_tool's requirements say 'malformed CSV', so the class is warranted."""
        errors = [{"name": "MalformedCSVError"}]
        kept = repairs.repair_unraised_errors(
            errors, [], "Handle missing files and malformed CSV input.", Log()
        )
        self.assertEqual([item["name"] for item in kept], ["MalformedCSVError"])

    def test_no_requirements_leaves_the_registry_untouched(self):
        errors = [{"name": "InvalidInputError"}]
        kept = repairs.repair_unraised_errors(errors, [], "", Log())
        self.assertEqual([item["name"] for item in kept], ["InvalidInputError"])

    def test_the_library_case_drops_two_and_keeps_one(self):
        errors = [
            {"name": "MalformedCSVError"},
            {"name": "InvalidInputError"},
            {"name": "OverdueLoanFoundError"},
        ]
        kept = repairs.repair_unraised_errors(errors, [], self.REQUIREMENTS, Log())
        self.assertEqual([item["name"] for item in kept], ["OverdueLoanFoundError"])


if __name__ == "__main__":
    unittest.main()
