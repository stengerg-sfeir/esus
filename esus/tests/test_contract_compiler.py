"""Closed-contract compilation: scalar graphs compile, open graphs refuse."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generator  # noqa: E402
from kernel import contract_compiler  # noqa: E402
from kernel.extraction import contracts  # noqa: E402


def field(name, type_="int", primary=False, nullable=False, fk=None):
    return {"name": name, "type": type_, "primary_key": primary,
            "nullable": nullable, "foreign_key": fk}


CTX = {
    "entity_names": ["Book", "Member", "Loan"],
    "models": [
        {"name": "Book", "fields": [
            field("id", primary=True), field("available_copies")]},
        {"name": "Member", "fields": [
            field("id", primary=True), field("name", "string")]},
        {"name": "Loan", "fields": [
            field("id", primary=True),
            field("book_id", fk={"target_entity": "Book"}),
            field("member_id", fk={"target_entity": "Member"}),
            field("loan_date", "date"), field("due_date", "date"),
            field("return_date", "date", nullable=True),
            field("status", "string")]},
    ],
    "repositories": [
        {"entity": "Book", "interface_name": "BookRepository", "methods": [
            {"name": "read_one", "params": [{"name": "id"}]},
            {"name": "update", "params": [{"name": "id"},
                                          {"name": "available_copies"}]}]},
        {"entity": "Member", "interface_name": "MemberRepository", "methods": [
            {"name": "read_one", "params": [{"name": "id"}]}]},
        {"entity": "Loan", "interface_name": "LoanRepository", "methods": [
            {"name": "read_one", "params": [{"name": "id"}]},
            {"name": "create", "params": [{"name": "book_id"},
                                          {"name": "member_id"},
                                          {"name": "loan_date"},
                                          {"name": "due_date"},
                                          {"name": "return_date"},
                                          {"name": "status"}]},
            {"name": "update", "params": [{"name": "id"},
                                          {"name": "return_date"},
                                          {"name": "status"}]}]},
    ],
    "errors": [{"name": "BookNotFoundError"},
               {"name": "MemberNotFoundError"},
               {"name": "LoanNotFoundError"},
               {"name": "NegativeAvailableCopiesError"},
               {"name": "AlreadyReturnedLoanError"}],
    "invariants": [],
}

BORROW = {
    "holder": "LibraryService", "method": "borrow_book",
    "bindings": [
        {"name": "book", "repository": "BookRepository", "method": "read_one",
         "args": ["book_id"], "error": "BookNotFoundError"},
        {"name": "member", "repository": "MemberRepository", "method": "read_one",
         "args": ["member_id"], "error": "MemberNotFoundError"},
    ],
    "preconditions": [
        {"check": "book exists", "error": "BookNotFoundError", "raise_when": "false"},
        {"check": "member exists", "error": "MemberNotFoundError", "raise_when": "false"},
        {"check": "book.available_copies < 1",
         "error": "NegativeAvailableCopiesError", "raise_when": "true"},
    ],
    "creates": [{"class": "Loan", "call": "LoanRepository.create", "fields": {
        "book_id": "param:book_id", "member_id": "param:member_id",
        "loan_date": "today", "due_date": "today+14d",
        "status": "literal:active"}}],
    "effects": [{"target": "book.available_copies", "op": "decrement",
                 "by": "1", "write": "BookRepository.update"}],
    "order": ["preconditions", "LoanRepository.create", "BookRepository.update"],
}

METHOD = {"name": "borrow_book", "params": [
    {"name": "member_id", "type": "int"}, {"name": "book_id", "type": "int"}],
    "return_type": "None"}


class ClosedCompilerTests(unittest.TestCase):
    def test_a_scalar_borrow_compiles_to_program_steps(self):
        program, reason = contract_compiler.compile_contract(BORROW, METHOD, CTX)
        self.assertIsNotNone(program, reason)
        self.assertEqual(reason, "closed scalar contract")
        text = "\n".join(generator._program_body(CTX, program))
        self.assertIn("book = self._repos['BookRepository'].read_one(book_id)", text)
        self.assertIn("self._repos['LoanRepository'].create", text)
        self.assertIn("due_date=datetime.date.today() + datetime.timedelta(days=14)", text)
        self.assertIn("self._repos['BookRepository'].update(book.id", text)

    def test_missing_create_fields_are_refused(self):
        contract = dict(BORROW)
        contract["creates"] = [{"class": "Loan", "call": "LoanRepository.create",
                                "fields": {"book_id": "param:book_id"}}]
        program, reason = contract_compiler.compile_contract(contract, METHOD, CTX)
        self.assertIsNone(program)
        self.assertIn("misses required field", reason)

    def test_a_collection_read_is_refused(self):
        contract = dict(BORROW)
        contract["reads"] = [{"entity": "Member", "field": "name"}]
        program, reason = contract_compiler.compile_contract(contract, METHOD, CTX)
        self.assertIsNone(program)
        self.assertIn("reads/derives", reason)

    def test_multiple_writes_without_order_are_refused(self):
        contract = dict(BORROW)
        contract["order"] = []
        program, reason = contract_compiler.compile_contract(contract, METHOD, CTX)
        self.assertIsNone(program)
        self.assertIn("explicit order", reason)

    def test_an_unresolved_effect_value_is_refused(self):
        contract = dict(BORROW)
        contract["effects"] = [{"target": "book.available_copies",
                                "op": "decrement", "by": "invented",
                                "write": "BookRepository.update"}]
        program, reason = contract_compiler.compile_contract(contract, METHOD, CTX)
        self.assertIsNone(program)
        self.assertIn("unresolvable", reason)

    def test_a_return_contract_compiles_with_related_book_read(self):
        method = {"name": "return_book", "params": [{"name": "loan_id", "type": "int"}],
                  "return_type": "None"}
        contract = {
            "holder": "LibraryService", "method": "return_book",
            "bindings": [
                {"name": "loan", "repository": "LoanRepository", "method": "read_one",
                 "args": ["loan_id"], "error": "LoanNotFoundError"},
                {"name": "book", "repository": "BookRepository", "method": "read_one",
                 "args": ["loan.book_id"], "error": "BookNotFoundError"},
            ],
            "preconditions": [
                {"check": "loan exists", "error": "LoanNotFoundError",
                 "raise_when": "false"},
            ],
            "effects": [
                {"target": "loan.return_date", "op": "set", "value": "now",
                 "write": "LoanRepository.update"},
                {"target": "loan.status", "op": "set", "value": "literal:returned",
                 "write": "LoanRepository.update"},
                {"target": "book.available_copies", "op": "increment", "by": "1",
                 "write": "BookRepository.update"},
            ],
            "order": ["preconditions", "LoanRepository.update", "BookRepository.update"],
        }
        program, reason = contract_compiler.compile_contract(contract, method, CTX)
        self.assertIsNotNone(program, reason)
        text = "\n".join(generator._program_body(CTX, program))
        self.assertIn("book = self._repos['BookRepository'].read_one(loan.book_id)", text)
        self.assertIn("self._repos['LoanRepository'].update(loan.id", text)
        self.assertIn("self._repos['BookRepository'].update(book.id", text)


class ContractNormalizationTests(unittest.TestCase):
    def test_bindings_and_create_fields_survive_normalization(self):
        record = contracts.normalize_contract(BORROW)
        self.assertEqual(record["bindings"][0]["name"], "book")
        self.assertEqual(record["creates"][0]["fields"]["due_date"], "today+14d")

    def test_unknown_fields_are_dropped(self):
        record = contracts.normalize_contract({
            "holder": "H", "method": "m",
            "bindings": [{"name": "x", "repository": "R",
                          "method": "read_one", "bogus": True}],
        })
        self.assertEqual(record["bindings"],
                         [{"name": "x", "repository": "R", "method": "read_one"}])


if __name__ == "__main__":
    unittest.main()
