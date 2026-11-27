"""Contract checks must prove the operation, not just find words in the body.

F-01: a `set` value must be the value assigned, not a string in a log.
F-02: a read must reach the related record's field through read dataflow.
F-03: a conditional `raise_when` must have a recognized conditional guard;
an unconditional raise is not evidence for the condition.
"""

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import generator  # noqa: E402


def complaints(body, contract, judge=None):
    return generator._contract_complaints(
        ast.parse(body), contract, judge=judge, body_text=body)


class SetValueProofTests(unittest.TestCase):
    CONTRACT = {
        "effects": [{
            "target": "order.status",
            "op": "set",
            "value": "'confirmed'",
            "write": "OrderRepository.update",
        }],
    }

    def test_a_decoy_string_in_a_log_does_not_satisfy_the_effect(self):
        found = complaints(
            "order.status = 'pending'\n"
            "self.log('confirmed')\n"
            "self._repos['OrderRepository'].update(order.id, status='pending')\n",
            self.CONTRACT)
        self.assertTrue(any("does not use that value" in item for item in found))

    def test_the_assigned_value_does_satisfy_the_effect(self):
        self.assertEqual(complaints(
            "order.status = 'confirmed'\n"
            "self._repos['OrderRepository'].update(order.id, status='confirmed')\n",
            self.CONTRACT), [])

    def test_a_field_expression_is_relative_to_the_target_object(self):
        contract = {
            "effects": [{
                "target": "member.is_active",
                "op": "set",
                "value": "not is_active",
                "write": "MemberRepository.update",
            }],
        }
        self.assertEqual(complaints(
            "member.is_active = not member.is_active\n"
            "self._repos['MemberRepository'].update(member.id, member)\n",
            contract), [])
        found = complaints(
            "member.is_active = not other.is_active\n"
            "self._repos['MemberRepository'].update(member.id, member)\n",
            contract)
        self.assertTrue(any("does not use that value" in item for item in found))

    def test_a_dynamic_expression_is_matched_only_on_the_rhs(self):
        contract = {
            "effects": [{
                "target": "loan.return_date",
                "op": "set",
                "value": "loan.due_date",
                "write": "LoanRepository.update",
            }],
        }
        found = complaints(
            "loan.return_date = datetime.datetime.now()\n"
            "self.log(loan.due_date)\n"
            "self._repos['LoanRepository'].update(loan.id, loan)\n",
            contract)
        self.assertTrue(any("does not use that value" in item for item in found))
        self.assertEqual(complaints(
            "loan.return_date = loan.due_date\n"
            "self._repos['LoanRepository'].update(loan.id, loan)\n",
            contract), [])


class StockEffectProofTests(unittest.TestCase):
    CONTRACT = {
        "effects": [{
            "target": "product.stock_quantity",
            "op": "decrement",
            "by": "quantity",
            "write": "ProductRepository.update",
        }],
    }

    def test_a_record_get_and_temporary_satisfy_the_decrement(self):
        body = (
            "item_row = item if isinstance(item, dict) else vars(item)\n"
            "product = self._repos['ProductRepository'].read_one("
            "product_id=item_row.get('product_id'))\n"
            "product_row = product if isinstance(product, dict) else vars(product)\n"
            "current_stock = product_row.get('stock_quantity', 0)\n"
            "new_stock = current_stock - item_row.get('quantity', 0)\n"
            "self._repos['ProductRepository'].update("
            "product_id=item_row.get('product_id'), "
            "stock_quantity=new_stock)\n")
        self.assertEqual(complaints(body, self.CONTRACT), [])

    def test_an_addition_does_not_satisfy_a_decrement(self):
        body = (
            "current_stock = product_row.get('stock_quantity', 0)\n"
            "new_stock = current_stock + quantity\n"
            "self._repos['ProductRepository'].update("
            "product_id=product_id, stock_quantity=new_stock)\n")
        self.assertTrue(any("does not decrement" in item
                            for item in complaints(body, self.CONTRACT)))


READ = {
    "entity": "Author",
    "field": "name",
    "repository": "AuthorRepository",
    "via": "Book.author_id",
}


class ReadProofTests(unittest.TestCase):
    def test_a_mentions_only_string_is_not_a_read(self):
        found = complaints(
            "author = self._repos['AuthorRepository'].read_one(1)\n"
            "print('name')\n",
            {"reads": [READ]})
        self.assertEqual(found, [
            "the confirmed contract reads `Author.name`, but the body never "
            "uses its `name`"])

    def test_a_read_alias_and_attribute_is_a_read(self):
        self.assertEqual(complaints(
            "author = self._repos['AuthorRepository'].read_one(1)\n"
            "return author.name\n", {"reads": [READ]}), [])

    def test_a_store_read_through_a_loop_is_a_read(self):
        self.assertEqual(complaints(
            "authors = self._store.select('Author', [])\n"
            "return [row['name'] for row in authors]\n",
            {"reads": [READ]}), [])

    def test_a_store_filter_on_the_field_is_a_read(self):
        self.assertEqual(complaints(
            "authors = self._store.select('Author', [('name', 'eq', name)])\n"
            "return authors\n", {"reads": [READ]}), [])


class RaiseProofTests(unittest.TestCase):
    PRECONDITION = {
        "check": "loan.status == 'returned'",
        "error": "AlreadyReturnedLoanError",
        "raise_when": "true",
    }

    def test_an_unconditional_raise_is_refused(self):
        found = generator._raise_when_complaints(
            ast.parse("raise errors.AlreadyReturnedLoanError('returned')"),
            self.PRECONDITION,
            judge=None,
            body_text="raise errors.AlreadyReturnedLoanError('returned')")
        self.assertEqual(len(found), 1)
        self.assertIn("without a recognized conditional guard", found[0])

    def test_the_matching_conditional_guard_is_accepted(self):
        body = (
            "if loan.status == 'returned':\n"
            "    raise errors.AlreadyReturnedLoanError('returned')\n")
        self.assertEqual(generator._raise_when_complaints(
            ast.parse(body), self.PRECONDITION, judge=None, body_text=body), [])


if __name__ == "__main__":
    unittest.main()
