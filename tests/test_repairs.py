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


if __name__ == "__main__":
    unittest.main()
