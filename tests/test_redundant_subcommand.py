"""A subcommand that repeats its parent's flags is asked, not deleted.

The extraction emitted `return loan --loan-id` beside the requested
`return --loan-id`: the model read a verb and its noun as two commands. The
review asks when both nodes take exactly the same flags and no requirements
line names the pair; the answer is recorded and applied like the duplicate-
node decisions. Each test pins a decision, silence included.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import review_surface  # noqa: E402
import test_surface  # noqa: E402


def option(name):
    return {"name": name, "short": None, "type": "int", "required": True,
            "default": None}


def node(name, flags=(), subs=()):
    return {"name": name, "options": [option(flag) for flag in flags],
            "subcommands": [{"name": sub, "options": [option(f) for f in fl]}
                            for sub, fl in subs]}


RETURN = [node("return", ["--loan-id"], [("loan", ["--loan-id"])])]


def collect(commands, requirements="library return --loan-id"):
    with tempfile.TemporaryDirectory() as directory:
        out = test_surface.writes(directory, commands, requirements)
        return review_surface.collect_duplicates(out)[0]


class Log:
    def __init__(self):
        self.lines = []

    def write(self, line):
        self.lines.append(line)


class DetectionTests(unittest.TestCase):
    def test_a_subcommand_repeating_its_parents_flags_is_asked(self):
        questions = collect(RETURN)
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]["kind"], "redundant")
        self.assertEqual((questions[0]["command"], questions[0]["subcommand"]),
                         ("return", "loan"))
        self.assertEqual(questions[0]["leaf_flags"], ["--loan-id"])

    def test_a_pair_the_requirements_name_is_not_asked(self):
        self.assertEqual(collect(
            RETURN, "Use `library return loan --loan-id` to return."), [])

    def test_different_flags_are_not_redundant(self):
        self.assertEqual(collect([node(
            "return", ["--loan-id"], [("loan", ["--loan-id", "--late"])])]), [])

    def test_a_parent_without_flags_is_not_redundant(self):
        self.assertEqual(collect([node("book", [], [("add", ["--title"])])]),
                         [])

    def test_a_subcommand_without_flags_is_not_redundant(self):
        self.assertEqual(collect([node("return", ["--loan-id"],
                                       [("loan", [])])]), [])

    def test_a_pair_already_asked_as_a_duplicate_is_not_asked_twice(self):
        commands = [
            node("borrow", ["--member-id"], [("book", ["--member-id"])]),
            node("book", [], [("add", ["--title"])])]
        questions = collect(commands, "library borrow --member-id")
        self.assertEqual([(q.get("kind", "duplicate"), q["command"],
                           q["subcommand"]) for q in questions],
                         [("duplicate", "borrow", "book")])

    def test_a_decided_pair_does_not_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            out = test_surface.writes(directory, RETURN,
                                      "library return --loan-id")
            review_surface.save_surface_decisions(out, [{
                "command": "return", "subcommand": "loan", "keep": "both",
                "kind": review_surface.REDUNDANT_KIND}])
            self.assertEqual(review_surface.collect_duplicates(out)[0], [])


class QuestionTests(unittest.TestCase):
    def question(self):
        return collect(RETURN)[0]

    def test_the_question_says_what_it_is(self):
        text = "\n".join(review_surface.describe_question(1, 1, self.question()))
        self.assertIn("REDUNDANT SUBCOMMAND: subcommand 'return loan'", text)
        self.assertIn("2) keep 'return' — drop the subcommand 'loan'", text)
        self.assertNotIn("3)", text)

    def test_the_answers(self):
        question = self.question()
        ask = lambda answer: review_surface.ask(question, lambda _: answer)
        self.assertEqual(ask("1"), review_surface.KEEP_BOTH)
        self.assertEqual(ask("2"), review_surface.KEEP_PARENT)
        self.assertIsNone(ask("3"))
        self.assertIsNone(ask("skip"))

    def test_the_prompt_offers_two_choices(self):
        seen = []
        review_surface.ask(self.question(), lambda prompt: seen.append(prompt)
                           or "1")
        self.assertEqual(seen, ["choose 1, 2, or skip: "])


class ApplyTests(unittest.TestCase):
    def components(self):
        return {"facade": {"invocation": {"commands": [
            node("return", ["--loan-id"], [("loan", ["--loan-id"])])]}}}

    def record(self, keep):
        return {"command": "return", "subcommand": "loan", "keep": keep,
                "kind": review_surface.REDUNDANT_KIND, "decided_by": "user"}

    def test_keeping_the_parent_drops_the_subcommand_and_says_why(self):
        log = Log()
        result = review_surface.apply_surface_decisions(
            self.components(), [self.record("parent")], log)
        command = result["facade"]["invocation"]["commands"][0]
        self.assertEqual(command["subcommands"], [])
        self.assertEqual([o["name"] for o in command["options"]], ["--loan-id"])
        self.assertIn("repeating its parent's flags", log.lines[0])

    def test_keeping_both_changes_nothing(self):
        result = review_surface.apply_surface_decisions(
            self.components(), [self.record("both")], Log())
        command = result["facade"]["invocation"]["commands"][0]
        self.assertEqual([s["name"] for s in command["subcommands"]], ["loan"])


if __name__ == "__main__":
    unittest.main()
