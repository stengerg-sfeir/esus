"""Preflight tests for generated grammars — no model required.

These cover the two layers that guard a runtime-built grammar:

  * `grammar_check` — rule syntax, undefined references, empty bodies;
  * `grammar_balance` — whether the literal brackets can ever close.

The balance cases are the two defects that silently emptied every
interaction_adapters document before they were fixed: a missing closing brace,
and a spurious opening brace from building an object tail with `json_object`.
Both were invisible to rule-syntax checking and to `LlamaGrammar.from_string`,
which does not parse its argument at all.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import (  # noqa: E402
    grammar_balance,
    grammar_builders,
    grammar_check,
    grammar_open,
    grammar_persistence,
    vocabulary,
)

STRING_RULE = 'string ::= "\\"" ([^"\\\\] | "\\\\" ["\\\\/bfnrt])* "\\""'
WS_RULE = "ws ::= [ \\t\\n]{0,2}"


class CheckAcceptsValidGrammars(unittest.TestCase):
    def test_open_grammars_pass(self):
        grammars = [
            grammar_open.phrase_list("intentions"),
            grammar_open.invariant_list("invariants"),
            grammar_open.data_models(),
            grammar_open.components(),
            grammar_open.service_contracts(),
            grammar_open.adapters(),
            grammar_open.persistence_ports(),
        ]
        for text in grammars:
            self.assertEqual(grammar_check.check(text), [])

    def test_closed_builders_pass_on_a_vocabulary(self):
        closed = vocabulary.Vocabulary(
            entities=vocabulary.entities_from(
                [{"name": "Book", "fields": [{"name": "id", "primary_key": True}]}]
            ),
            services=vocabulary.services_from(
                [{"service_name": "BookService", "methods": [{"name": "add_book", "params": []}]}]
            ),
            crud_entities=("Book",),
        )
        for text in (
            grammar_builders.components(closed),
            grammar_builders.adapters(closed),
            grammar_persistence.persistence_ports(closed),
        ):
            self.assertEqual(grammar_check.check(text), [])


class CheckRejectsMalformedGrammars(unittest.TestCase):
    def test_undefined_reference(self):
        text = "root ::= missing-rule"
        self.assertTrue(
            any("undefined rule" in problem for problem in grammar_check.check(text))
        )

    def test_empty_body(self):
        text = "root ::= \nws ::= [ ]"
        self.assertTrue(
            any("empty body" in problem for problem in grammar_check.check(text))
        )

    def test_unterminated_literal(self):
        text = 'root ::= "unclosed'
        self.assertTrue(
            any("unterminated" in problem for problem in grammar_check.check(text))
        )

    def test_unclosed_alternation(self):
        text = 'root ::= "a" |'
        self.assertTrue(
            any("alternation" in problem for problem in grammar_check.check(text))
        )

    def test_missing_root(self):
        text = 'other ::= "a"'
        self.assertTrue(
            any("no 'root'" in problem for problem in grammar_check.check(text))
        )

    def test_assert_valid_raises(self):
        with self.assertRaises(grammar_check.GrammarError):
            grammar_check.assert_valid("root ::= missing-rule", label="test")


class BalanceCatchesUnclosableObjects(unittest.TestCase):
    """The two shapes that emptied every adapter list."""

    def test_missing_closing_brace(self):
        text = "\n".join(
            [
                'root ::= "{" ws "\\"a\\"" ws ":" ws pair ws "}"',
                'pair ::= "{" ws "\\"b\\"" ws ":" ws string',
                STRING_RULE,
                WS_RULE,
            ]
        )
        problems = grammar_balance.check(text)
        self.assertTrue(problems, "a pair that never closes must be rejected")
        self.assertIn("2 '{'", problems[0])

    def test_spurious_opening_brace(self):
        text = "\n".join(
            [
                'root ::= "{" ws "\\"a\\"" ws ":" ws pair ws "}"',
                'pair ::= "{" ws "\\"b\\"" ws ":" ws string ws "," ws inner',
                'inner ::= "{" ws "\\"c\\"" ws ":" ws string ws "}"',
                STRING_RULE,
                WS_RULE,
            ]
        )
        problems = grammar_balance.check(text)
        self.assertTrue(problems, "a pair that opens twice must be rejected")
        self.assertIn("3 '{'", problems[0])

    def test_balanced_object_accepted(self):
        text = "\n".join(
            [
                'root ::= "{" ws "\\"a\\"" ws ":" ws pair ws "}"',
                'pair ::= "{" ws "\\"b\\"" ws ":" ws string ws "}"',
                STRING_RULE,
                WS_RULE,
            ]
        )
        self.assertEqual(grammar_balance.check(text), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
