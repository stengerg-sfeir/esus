"""Tests for the four rules added to close blind spots §3, §4 and §5.

§3 — a claimed crud operation with no method implementing it.
§4 — a primary key marked non-unique; an invariant contradicting its field.
§5 — a pattern id outside the catalogues; a confidence outside the range.
"""

import unittest

from kernel.consistency.checks_crud import check_crud_coverage
from kernel.consistency.checks_invariants import check_invariant_claims
from kernel.consistency.checks_patterns import check_pattern_matches
from kernel.consistency.naming import EntityIndex
from kernel.consistency.report import Report


def rules_fired(report):
    return [finding.rule for finding in report.findings]


def method(name, params=()):
    return {
        "name": name,
        "description": "does a thing",
        "params": [{"name": p, "type": "int"} for p in params],
        "return_type": "Result",
    }


class CrudCoverageTests(unittest.TestCase):
    """§3: an operation nothing implements."""

    def check(self, operations, entity="Book", repository="Book", methods=None):
        documents = {
            "components": {
                "crud_services": [{"entity": entity, "operations": operations}]
            },
            "service_contracts": [],
            "persistence_ports": {
                "repositories": [
                    {
                        "entity": repository,
                        "interface_name": "BookRepository",
                        "methods": methods if methods is not None else [method("add_book", ("title",))],
                    }
                ]
            },
        }
        report = Report("test")
        check_crud_coverage(documents["components"], documents, report)
        return report

    def test_a_delete_with_no_delete_method_is_flagged(self):
        report = self.check(["create", "delete"])
        self.assertIn("unmet_crud_operation", rules_fired(report))
        self.assertIn("delete", report.warnings[0].message)

    def test_create_is_satisfied_by_an_add_prefixed_method(self):
        self.assertNotIn("unmet_crud_operation", rules_fired(self.check(["create"])))

    def test_create_is_satisfied_by_a_create_prefixed_method(self):
        report = self.check(["create"], methods=[method("create_book", ("title",))])
        self.assertNotIn("unmet_crud_operation", rules_fired(report))

    def test_read_and_update_are_not_checked(self):
        """Their prefixes are ambiguous, so the rule stays silent rather than guess."""
        for operations in (["read_one"], ["read_all"], ["update"]):
            with self.subTest(operations=operations):
                self.assertNotIn("unmet_crud_operation", rules_fired(self.check(operations)))

    def test_an_entity_with_no_repository_is_not_flagged(self):
        """`no_repository` covers that; there is nothing to compare against here."""
        report = self.check(["create", "delete"], entity="Missing", repository="Book")
        self.assertNotIn("unmet_crud_operation", rules_fired(report))

    def test_a_service_named_for_the_entity_also_counts(self):
        documents = {
            "components": {"crud_services": [{"entity": "Book", "operations": ["delete"]}]},
            "service_contracts": [
                {"service_name": "BookRepository", "methods": [method("delete_book", ("book_id",))]}
            ],
            "persistence_ports": {"repositories": []},
        }
        report = Report("test")
        check_crud_coverage(documents["components"], documents, report)
        self.assertNotIn("unmet_crud_operation", rules_fired(report))


def model(name, fields):
    return {"name": name, "fields": fields}


def field(name, **attributes):
    base = {"name": name, "type": "int", "primary_key": False, "nullable": False, "unique": False}
    base.update(attributes)
    return base


class InvariantClaimTests(unittest.TestCase):
    """§4: an invariant that contradicts the field it names.

    Invariants are tagged objects now, so the helper wraps each sentence the way
    step C writes it. A bare string is exercised too, because the readers still
    accept the older output directories.
    """

    def check(self, invariants, models):
        tagged = [{"text": text, "kind": "schema"} for text in invariants]
        report = Report("test")
        check_invariant_claims(tagged, EntityIndex.from_models(models), report)
        return report

    def test_a_bare_string_is_still_read(self):
        """The pre-tagging shape must keep working for old output directories."""
        report = Report("test")
        check_invariant_claims(
            ["sku must be unique across all products"],
            EntityIndex.from_models([model("Product", [field("sku", unique=False)])]),
            report,
        )
        self.assertIn("inconsistent_invariant", rules_fired(report))

    def test_a_unique_claim_on_a_non_unique_field_is_flagged(self):
        report = self.check(
            ["sku must be unique across all products"],
            [model("Product", [field("sku", unique=False)])],
        )
        self.assertIn("inconsistent_invariant", rules_fired(report))

    def test_an_agreeing_claim_is_not_flagged(self):
        report = self.check(
            ["sku must be unique across all products"],
            [model("Product", [field("sku", unique=True)])],
        )
        self.assertNotIn("inconsistent_invariant", rules_fired(report))

    def test_a_nullable_claim_on_a_non_nullable_field_is_flagged(self):
        report = self.check(
            ["category_id must be nullable if not enforced by a foreign key"],
            [model("Product", [field("category_id", nullable=False)])],
        )
        self.assertIn("inconsistent_invariant", rules_fired(report))

    def test_an_ambiguous_field_name_is_skipped(self):
        """Two models declare `name`, so the invariant does not identify one."""
        report = self.check(
            ["name must be unique"],
            [
                model("Category", [field("name", unique=False)]),
                model("Product", [field("name", unique=False)]),
            ],
        )
        self.assertNotIn("inconsistent_invariant", rules_fired(report))

    def test_an_unknown_field_name_is_skipped(self):
        """A program with no data model may state rules about records it does not model."""
        report = self.check(["isbn must be unique across all records"], [])
        self.assertNotIn("inconsistent_invariant", rules_fired(report))

    def test_an_invariant_claiming_neither_attribute_is_ignored(self):
        report = self.check(
            ["low_active must be a boolean"],
            [model("Product", [field("low_active", type="boolean")])],
        )
        self.assertNotIn("inconsistent_invariant", rules_fired(report))


class PatternMatchTests(unittest.TestCase):
    """§5: the document nothing read."""

    def check(self, matches, services=()):
        documents = {"service_contracts": list(services)}
        report = Report("test")
        check_pattern_matches(matches, documents, report)
        return report

    def test_a_pattern_id_outside_the_catalogues_is_flagged(self):
        report = self.check([{"pattern_id": "MADE_UP", "source": "invariant",
                              "text": "x", "confidence": 0.9}])
        self.assertIn("unknown_reference", rules_fired(report))

    def test_a_catalogue_pattern_id_is_accepted(self):
        report = self.check([{"pattern_id": "AGGREGATE_BY_FK", "source": "invariant",
                              "text": "x", "confidence": 0.9}])
        self.assertNotIn("unknown_reference", rules_fired(report))

    def test_a_confidence_outside_the_range_is_an_error(self):
        for confidence in (1.4, -0.1, "high", None):
            with self.subTest(confidence=confidence):
                report = self.check([{"pattern_id": "AGGREGATE_BY_FK", "source": "invariant",
                                      "text": "x", "confidence": confidence}])
                self.assertIn("invalid_value", rules_fired(report))

    def test_a_low_confidence_is_reported(self):
        report = self.check([{"pattern_id": "AGGREGATE_BY_FK", "source": "invariant",
                              "text": "x", "confidence": 0.11}])
        self.assertIn("low_confidence", rules_fired(report))

    def test_a_contract_source_must_resolve(self):
        entry = {"pattern_id": "AGGREGATE_BY_FK", "source": "contract:Thing.add",
                 "text": "x", "confidence": 0.9}
        self.assertIn("unknown_reference", rules_fired(self.check([entry])))

    def test_a_resolving_contract_source_is_accepted(self):
        entry = {"pattern_id": "AGGREGATE_BY_FK", "source": "contract:WineService.add_wine",
                 "text": "x", "confidence": 0.9}
        services = [{"service_name": "WineService", "methods": [method("add_wine")]}]
        self.assertNotIn("unknown_reference", rules_fired(self.check([entry], services)))

    def test_an_unrecognised_source_is_an_error(self):
        report = self.check([{"pattern_id": "AGGREGATE_BY_FK", "source": "guesswork",
                              "text": "x", "confidence": 0.9}])
        self.assertIn("unsupported_value", rules_fired(report))

    def test_an_absent_document_is_not_an_error(self):
        self.assertEqual(rules_fired(self.check(None)), [])


if __name__ == "__main__":
    unittest.main()
