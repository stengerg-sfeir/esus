"""Tests for the two rules that close blind spots §1 and §2 of BLIND_SPOTS.md.

§1 — a repository named the same in `service_contracts` and `persistence_ports`
     must declare the same methods.
§2 — a method whose name promises an argument must declare one.
"""

import unittest

from kernel.consistency.checks_interfaces import check_interface_agreement
from kernel.consistency.methods import check_method_list
from kernel.consistency.report import Report


def method(name, params=()):
    """One method entry, with `params` given as parameter names."""
    return {
        "name": name,
        "description": "does a thing",
        "params": [{"name": p, "type": "int"} for p in params],
        "return_type": "Result",
    }


def rules_fired(report):
    return [finding.rule for finding in report.findings]


class MissingParametersTests(unittest.TestCase):
    """§2: a name that promises an argument cannot declare none."""

    def check(self, name, params=()):
        report = Report("test")
        check_method_list([method(name, params)], "repo", report)
        return report

    def test_write_verb_without_params_is_flagged(self):
        self.assertIn("missing_parameters", rules_fired(self.check("create")))
        self.assertIn("missing_parameters", rules_fired(self.check("save_wine")))
        self.assertIn("missing_parameters", rules_fired(self.check("delete_member")))

    def test_lookup_by_key_without_params_is_flagged(self):
        self.assertIn("missing_parameters", rules_fired(self.check("get_wine_by_id")))
        self.assertIn("missing_parameters", rules_fired(self.check("find_by_name")))
        self.assertIn("missing_parameters", rules_fired(self.check("get_member_by_email")))

    def test_a_declared_parameter_satisfies_the_rule(self):
        self.assertNotIn("missing_parameters", rules_fired(self.check("create", ("name",))))
        self.assertNotIn(
            "missing_parameters", rules_fired(self.check("get_wine_by_id", ("wine_id",)))
        )

    def test_listing_everything_needs_no_parameter(self):
        for name in ("get_all_wines", "get_all_categories", "find_all", "list_products"):
            with self.subTest(name=name):
                self.assertNotIn("missing_parameters", rules_fired(self.check(name)))

    def test_aggregates_are_exempt(self):
        """`by_category` in an aggregate means "grouped by", which takes no argument."""
        for name in (
            "get_total_stock_value_by_category",
            "stock_value_by_category",
            "low_stock_report",
            "get_monthly_expense_summary",
        ):
            with self.subTest(name=name):
                self.assertNotIn("missing_parameters", rules_fired(self.check(name)))

    def test_a_predicate_in_the_name_needs_no_parameter(self):
        """`get_active_members` reads as a fixed predicate, not a keyed lookup."""
        self.assertNotIn("missing_parameters", rules_fired(self.check("get_active_members")))
        self.assertNotIn("missing_parameters", rules_fired(self.check("get_overdue_loans")))


class InterfaceAgreementTests(unittest.TestCase):
    """§1: one repository, two documents, one method set."""

    def check(self, services, repositories):
        report = Report("test")
        documents = {
            "service_contracts": [
                {"service_name": name, "methods": methods} for name, methods in services
            ],
            "persistence_ports": {
                "repositories": [
                    {"entity": entity, "interface_name": name, "methods": methods}
                    for name, entity, methods in repositories
                ]
            },
        }
        check_interface_agreement(documents, report)
        return report

    def test_identical_method_sets_pass(self):
        shared = [method("get_wine_by_id", ("wine_id",)), method("create_wine", ("name",))]
        report = self.check([("WineRepository", shared)], [("WineRepository", "Wine", shared)])
        self.assertNotIn("inconsistent_interface", rules_fired(report))

    def test_divergent_method_sets_are_flagged(self):
        report = self.check(
            [("WineRepository", [method("create_wine", ("name",)), method("delete_wine", ("wine_id",))])],
            [("WineRepository", "Wine", [method("save_wine", ("name",))])],
        )
        self.assertIn("inconsistent_interface", rules_fired(report))
        message = report.warnings[0].message
        self.assertIn("create_wine", message)
        self.assertIn("save_wine", message)

    def test_a_service_is_not_confused_with_a_repository(self):
        """`WineService` and `WineRepository` are different interfaces, not a divergence."""
        report = self.check(
            [("WineService", [method("borrow_wine", ("wine_id",))])],
            [("WineRepository", "Wine", [method("save_wine", ("name",))])],
        )
        self.assertNotIn("inconsistent_interface", rules_fired(report))

    def test_an_interface_in_one_document_only_is_not_a_divergence(self):
        report = self.check(
            [("BottleRepository", [method("save_bottle", ("name",))])],
            [("WineRepository", "Wine", [method("save_wine", ("name",))])],
        )
        self.assertNotIn("inconsistent_interface", rules_fired(report))

    def test_casing_differences_do_not_count_as_divergence(self):
        report = self.check(
            [("WineRepository", [method("get_all_wines")])],
            [("winerepository", "Wine", [method("get_all_wines")])],
        )
        self.assertNotIn("inconsistent_interface", rules_fired(report))


if __name__ == "__main__":
    unittest.main()
