"""A repository create must be able to set every required field.

`LoanRepository.create` described `due_date` and `status` and took neither,
so every create failed the NOT NULL constraint. The repair adds a parameter
only when the method's own description names the field; the probe reports any
required field no create can still reach. Each test pins a decision, silence
included.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import probe_readiness  # noqa: E402
from kernel.extraction import repairs  # noqa: E402


class Log:
    def __init__(self):
        self.lines = []

    def write(self, line):
        self.lines.append(line)


def field(name, type_="string", nullable=False, primary_key=False):
    return {"name": name, "type": type_, "primary_key": primary_key,
            "nullable": nullable, "unique": False, "foreign_key": None,
            "status": "explicit"}


LOAN = {"name": "Loan", "fields": [
    field("id", "int", primary_key=True),
    field("book_id", "int"), field("loan_date", "date"),
    field("due_date", "date"), field("return_date", "date", nullable=True),
    field("status")]}


def ports(description, params):
    return {"repositories": [{
        "entity": "Loan", "interface_name": "LoanRepository",
        "methods": [{"name": "create", "description": description,
                     "params": params, "return_type": "int"}]}]}


BASE = [{"name": "book_id", "type": "int"},
        {"name": "loan_date", "type": "date"}]


def names(document):
    return [p["name"] for p in
            document["repositories"][0]["methods"][0]["params"]]


class RepairTests(unittest.TestCase):
    def test_a_described_required_field_becomes_a_parameter(self):
        document = ports("Creates a loan with book_id, loan_date, due_date "
                         "(14 days later), and status (active).", list(BASE))
        repairs.repair_create_missing_fields(document, [LOAN], Log())
        self.assertEqual(names(document),
                         ["book_id", "loan_date", "due_date", "status"])
        self.assertEqual(document["repositories"][0]["methods"][0]
                         ["params"][2]["type"], "date")
        self.assertEqual(document["repositories"][0]["methods"][0]
                         ["params"][3]["type"], "str")

    def test_a_field_the_description_does_not_name_is_left_alone(self):
        document = ports("Creates a loan with book_id and loan_date.",
                         list(BASE))
        repairs.repair_create_missing_fields(document, [LOAN], Log())
        self.assertEqual(names(document), ["book_id", "loan_date"])

    def test_a_nullable_or_key_field_is_never_added(self):
        document = ports("Creates a loan; sets id and return_date too.",
                         list(BASE))
        repairs.repair_create_missing_fields(document, [LOAN], Log())
        self.assertEqual(names(document), ["book_id", "loan_date"])

    def test_a_field_already_a_parameter_is_not_added_twice(self):
        document = ports("Creates a loan with due_date.",
                         BASE + [{"name": "due_date", "type": "date"}])
        repairs.repair_create_missing_fields(document, [LOAN], Log())
        self.assertEqual(names(document).count("due_date"), 1)

    def test_a_create_taking_the_whole_entity_is_left_alone(self):
        document = ports("Creates a loan with due_date.",
                         [{"name": "loan", "type": "Loan"}])
        repairs.repair_create_missing_fields(document, [LOAN], Log())
        self.assertEqual(names(document), ["loan"])

    def test_other_methods_are_left_alone(self):
        document = ports("Updates due_date.", list(BASE))
        document["repositories"][0]["methods"][0]["name"] = "update"
        repairs.repair_create_missing_fields(document, [LOAN], Log())
        self.assertEqual(names(document), ["book_id", "loan_date"])

    def test_every_addition_is_logged(self):
        log = Log()
        document = ports("Creates a loan with due_date.", list(BASE))
        repairs.repair_create_missing_fields(document, [LOAN], log)
        self.assertEqual(len(log.lines), 1)
        self.assertIn("due_date", log.lines[0])


class CreateKeyParameterTests(unittest.TestCase):
    model = {"name": "Category", "fields": [
        field("category_id", "int", primary_key=True),
        field("name")]}

    def holder(self, description):
        return [{"service_name": "CategoryService", "methods": [{
            "name": "add_category",
            "description": description,
            "params": [{"name": "category_id", "type": "int"},
                       {"name": "name", "type": "str"}],
            "return_type": "None"}]}]

    def test_a_service_create_loses_its_store_generated_key(self):
        services = self.holder("Adds a new category with a specified name.")
        repairs.repair_create_key_parameters(services, [self.model], Log())
        self.assertEqual(
            [p["name"] for p in services[0]["methods"][0]["params"]],
            ["name"])

    def test_a_description_naming_the_key_keeps_it(self):
        services = self.holder("Adds a category with a given category_id.")
        repairs.repair_create_key_parameters(services, [self.model], Log())
        self.assertEqual(
            [p["name"] for p in services[0]["methods"][0]["params"]],
            ["category_id", "name"])

    def test_a_repository_create_is_left_alone(self):
        repositories = [{"interface_name": "CategoryRepository", "methods": [{
            "name": "create",
            "description": "Creates a Category.",
            "params": [{"name": "category_id", "type": "int"},
                       {"name": "name", "type": "str"}],
            "return_type": "Category"}]}]
        repairs.repair_create_key_parameters(
            repositories, [self.model], Log())
        self.assertEqual(
            [p["name"] for p in repositories[0]["methods"][0]["params"]],
            ["category_id", "name"])


class TotalCountParameterTests(unittest.TestCase):
    model = {"name": "User", "fields": [
        field("user_id", "int", primary_key=True),
        field("status")]}

    def test_a_total_count_loses_a_spurious_key(self):
        holders = [{"interface_name": "UserRepository", "methods": [{
            "name": "get_user_count",
            "description": "Count the total number of users in the system.",
            "params": [{"name": "user_id", "type": "int"}],
            "return_type": "int"}]}]
        repairs.repair_total_count_parameters(holders, [self.model], Log())
        self.assertEqual(holders[0]["methods"][0]["params"], [])

    def test_a_filtered_count_keeps_its_key(self):
        holders = [{"interface_name": "UserRepository", "methods": [{
            "name": "get_active_user_count",
            "description": "Count the number of active users.",
            "params": [{"name": "user_id", "type": "int"}],
            "return_type": "int"}]}]
        repairs.repair_total_count_parameters(holders, [self.model], Log())
        self.assertEqual(
            [p["name"] for p in holders[0]["methods"][0]["params"]],
            ["user_id"])


class ProbeTests(unittest.TestCase):
    def findings(self, document, requirements=""):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data_models.json").write_text(
                json.dumps({"data_models": [LOAN]}))
            (root / "persistence_ports.json").write_text(
                json.dumps({"persistence_ports": document}))
            (root / "requirements.txt").write_text(requirements)
            return probe_readiness.create_field_findings(str(root))

    def test_unreachable_required_fields_are_reported(self):
        found = self.findings(ports("Creates a loan.", list(BASE)))
        text = " ".join(item.message for item in found)
        self.assertIn("Loan.due_date", text)
        self.assertIn("Loan.status", text)
        self.assertEqual({item.rule for item in found},
                         {"create_field_unreachable"})

    def test_a_repaired_create_is_silent(self):
        document = ports("Creates a loan with due_date and status.",
                         list(BASE))
        repairs.repair_create_missing_fields(document, [LOAN], Log())
        self.assertEqual(self.findings(document), [])

    def test_a_default_in_the_requirements_is_silent(self):
        found = self.findings(
            ports("Creates a loan.",
                  BASE + [{"name": "due_date", "type": "date"}]),
            "Loan: status (default 'active')")
        self.assertEqual(found, [])

    def test_a_default_of_none_does_not_satisfy_a_required_field(self):
        found = self.findings(
            ports("Creates a loan.",
                  BASE + [{"name": "due_date", "type": "date"}]),
            "Loan: status (default None)")
        self.assertIn("Loan.status", " ".join(i.message for i in found))


if __name__ == "__main__":
    unittest.main()
