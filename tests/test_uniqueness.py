"""Uniqueness provenance, decisions, and invariant alignment."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kernel.extraction import uniqueness  # noqa: E402
import generator  # noqa: E402


def models(**field):
    field = {"name": "email", "type": "string", "unique": True, **field}
    return [{"name": "Contact", "fields": [
        {"name": "id", "type": "int", "primary_key": True, "unique": True},
        field,
    ]}]


class ProvenanceTests(unittest.TestCase):
    def test_a_rejected_unique_flag_is_cleared(self):
        body = models(unique=True, unique_status="rejected")
        uniqueness.classify_unique_fields(body, "")
        field = body[0]["fields"][1]
        self.assertFalse(field["unique"])
        self.assertEqual(field["unique_status"], "rejected")

    def test_a_prompt_statement_is_explicit(self):
        body = models()
        uniqueness.classify_unique_fields(
            body, "Every contact email address must be unique.")
        self.assertEqual(body[0]["fields"][1]["unique_status"],
                         uniqueness.EXPLICIT)

    def test_a_field_name_guess_is_inferred_and_kept_as_evidence(self):
        body = models()
        uniqueness.classify_unique_fields(body, "A contact has an email.")
        field = body[0]["fields"][1]
        self.assertEqual(field["unique_status"], uniqueness.INFERRED)
        self.assertTrue(field["unique"])
        self.assertFalse(uniqueness.is_enforced(field))

    def test_a_parenthetical_unique_annotation_is_explicit(self):
        body = models()
        uniqueness.classify_unique_fields(
            body, "Contact model — id, name, email (unique), phone.")
        self.assertEqual(body[0]["fields"][1]["unique_status"],
                         uniqueness.EXPLICIT)

    def test_unique_identifier_is_not_a_field_statement(self):
        body = models(name="title")
        body[0]["fields"][1]["unique"] = True
        uniqueness.classify_unique_fields(
            body, "Every contact has a unique identifier and a title.")
        self.assertEqual(body[0]["fields"][1]["unique_status"],
                         uniqueness.INFERRED)

    def test_a_composite_key_is_not_per_field_uniqueness(self):
        body = [{"name": "Budget", "fields": [
            {"name": "id", "type": "int", "primary_key": True, "unique": True},
            {"name": "category_id", "type": "int"},
            {"name": "month", "type": "string", "unique": True},
        ]}]
        uniqueness.classify_unique_fields(
            body, "UNIQUE(category_id, month) must be unique together.")
        self.assertEqual(body[0]["fields"][2]["unique_status"],
                         uniqueness.INFERRED)

    def test_primary_keys_are_explicit(self):
        body = models()
        uniqueness.classify_unique_fields(body, "")
        self.assertEqual(body[0]["fields"][0]["unique_status"],
                         uniqueness.EXPLICIT)

    def test_legacy_fields_without_status_remain_enforced(self):
        field = {"name": "email", "unique": True}
        self.assertEqual(uniqueness.field_status(field), uniqueness.EXPLICIT)
        self.assertTrue(uniqueness.is_enforced(field))


class DecisionTests(unittest.TestCase):
    def test_a_confirmation_is_applied_and_stamped(self):
        body = models()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requirements.txt"
            path.write_text("A contact has an email.\n", encoding="utf-8")
            requirements = path.read_text(encoding="utf-8")
            sha = uniqueness.requirements_sha(requirements)
            uniqueness.save_decisions(directory, [{
                "entity": "Contact", "field": "email", "unique": True,
                "requirements_sha": sha,
            }])
            uniqueness.finalize(
                body, [{"text": "Contact.email must be unique"}],
                directory, requirements)
        self.assertEqual(body[0]["fields"][1]["unique_status"],
                         uniqueness.CONFIRMED)
        self.assertTrue(uniqueness.is_enforced(body[0]["fields"][1]))

    def test_a_rejection_sets_unique_false(self):
        body = models()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requirements.txt"
            path.write_text("A contact has an email.\n", encoding="utf-8")
            requirements = path.read_text(encoding="utf-8")
            sha = uniqueness.requirements_sha(requirements)
            uniqueness.save_decisions(directory, [{
                "entity": "Contact", "field": "email", "unique": False,
                "requirements_sha": sha,
            }])
            uniqueness.apply_decisions(
                body, uniqueness.load_decisions(directory),
                requirements_text=requirements)
        self.assertFalse(body[0]["fields"][1]["unique"])
        self.assertEqual(body[0]["fields"][1]["unique_status"],
                         uniqueness.REJECTED)

    def test_a_decision_under_an_old_prompt_is_not_applied(self):
        body = models()
        record = {"entity": "Contact", "field": "email", "unique": True,
                  "requirements_sha": "old"}
        uniqueness.apply_decisions(
            body, [record], requirements_text="new requirements")
        self.assertTrue(body[0]["fields"][1]["unique"])
        self.assertNotEqual(body[0]["fields"][1].get("unique_status"),
                            uniqueness.CONFIRMED)


class InvariantTests(unittest.TestCase):
    def test_inferred_unique_line_is_removed(self):
        body = models()
        uniqueness.classify_unique_fields(body, "A contact has an email.")
        invariants = [
            {"text": "Contact.email must be unique", "kind": "schema"},
            {"text": "A contact must have an email", "kind": "rule"},
        ]
        kept = uniqueness.filter_invariants(body, invariants)
        self.assertEqual([item["text"] for item in kept],
                         ["A contact must have an email"])

    def test_explicit_unique_line_is_kept_and_added(self):
        body = models()
        uniqueness.classify_unique_fields(
            body, "Contact.email must be unique.")
        kept = uniqueness.filter_invariants(body, [])
        kept = uniqueness.ensure_invariants(body, kept)
        self.assertEqual([item["text"] for item in kept],
                         ["Contact.email must be unique"])

    def test_a_composite_constraint_line_is_untouched(self):
        body = [{"name": "Budget", "fields": [
            {"name": "category_id", "type": "int"},
            {"name": "month", "type": "string"},
        ]}]
        invariants = [{"text": "Budget must have a unique constraint on "
                               "(category_id, month)"}]
        kept = uniqueness.filter_invariants(body, invariants)
        self.assertEqual(kept, invariants)


class GeneratorTests(unittest.TestCase):
    def ctx(self, status):
        return {
            "models": [{"name": "Contact", "fields": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "email", "type": "string", "unique": True,
                 "unique_status": status},
            ]}],
            "invariants": [{"text": "Contact.email must be unique"}],
            "requirements": "",
        }

    def test_inferred_unique_is_not_enforced_or_schematised(self):
        ctx = self.ctx(uniqueness.INFERRED)
        self.assertEqual(generator._unique_fields(ctx, "Contact"), [])
        namespace = {}
        exec(generator.emit_schema(ctx), namespace)  # noqa: S102
        email = next(field for field in namespace["SCHEMA"]["Contact"]["fields"]
                     if field["name"] == "email")
        self.assertFalse(email["unique"])

    def test_explicit_unique_is_enforced_and_schematised(self):
        ctx = self.ctx(uniqueness.EXPLICIT)
        self.assertEqual(generator._unique_fields(ctx, "Contact"), ["email"])
        namespace = {}
        exec(generator.emit_schema(ctx), namespace)  # noqa: S102
        email = next(field for field in namespace["SCHEMA"]["Contact"]["fields"]
                     if field["name"] == "email")
        self.assertTrue(email["unique"])


def _runtime_worker():
    path = ROOT / "tests" / "runtime" / "worker.py"
    spec = importlib.util.spec_from_file_location(
        "esus_runtime_worker_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AcceptancePolicyTests(unittest.TestCase):
    def test_inferred_uniqueness_is_not_asserted_either_way(self):
        worker = _runtime_worker()
        self.assertIsNone(worker._unique_asserted(
            {"unique": True, "unique_status": "inferred"}))
        self.assertIsNone(worker._unique_asserted(
            {"unique": False, "unique_status": "inferred"}))

    def test_explicit_and_rejected_uniqueness_are_asserted(self):
        worker = _runtime_worker()
        self.assertTrue(worker._unique_asserted(
            {"unique": True, "unique_status": "explicit"}))
        self.assertFalse(worker._unique_asserted(
            {"unique": False, "unique_status": "rejected"}))


class SidecarTests(unittest.TestCase):
    def test_decisions_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            uniqueness.save_decisions(directory, [{"entity": "C",
                                                   "field": "email",
                                                   "unique": True}])
            self.assertEqual(
                uniqueness.load_decisions(directory)[0]["field"], "email")
            self.assertTrue(
                (Path(directory) / "unique_decisions.json").is_file())

    def test_inferred_fields_are_grouped_for_review(self):
        body = models()
        body[0]["fields"].append(
            {"name": "name", "type": "string", "unique": True})
        uniqueness.classify_unique_fields(body, "A contact has an email.")
        fields = uniqueness.inferred_fields(body)
        self.assertEqual([field["policy"] for field in fields],
                         ["conventional", "display"])


if __name__ == "__main__":
    unittest.main()
