"""The pipeline enumerates what the model must cover; the checker verifies it.

Each test pins one inclusion or exclusion, because a line wrongly listed
becomes an instruction to invent, and a line wrongly dropped stays
undiscovered — the two failure modes this module exists to separate.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import command_lines, prompts  # noqa: E402


class ExtractTests(unittest.TestCase):
    def test_flagged_lines_are_listed_verbatim(self):
        spans = command_lines.extract_command_lines(
            "Run `product add --sku --name` or `product list [--x]`.")
        self.assertEqual(spans, ["product add --sku --name",
                                 "product list [--x]"])

    def test_a_bare_two_word_line_is_listed(self):
        self.assertEqual(command_lines.extract_command_lines("Run `library overdue`."),
                         ["library overdue"])
        self.assertEqual(command_lines.extract_command_lines("See `category list`."),
                         ["category list"])

    def test_schema_fragments_are_not_command_lines(self):
        self.assertEqual(
            command_lines.extract_command_lines("With `UNIQUE(category_id, month)`."), [])
        self.assertEqual(
            command_lines.extract_command_lines("A `month TEXT UNIQUE` column."), [])

    def test_flagless_multi_word_lines_stay_with_the_model(self):
        """`product report low-stock` names no flag: judgment, not a listing."""
        self.assertEqual(
            command_lines.extract_command_lines("Run `product report low-stock`."), [])

    def test_repeated_lines_are_listed_once(self):
        spans = command_lines.extract_command_lines(
            "Run `a add --x` then `a add --x`.")
        self.assertEqual(spans, ["a add --x"])

    def test_prose_without_backticks_yields_nothing(self):
        self.assertEqual(
            command_lines.extract_command_lines("Search orders by customer."), [])
        self.assertEqual(command_lines.extract_command_lines(""), [])
        self.assertEqual(command_lines.extract_command_lines(None), [])

    def test_full_prompts_yield_their_command_lines(self):
        here = Path(__file__).resolve().parent.parent
        counts = {}
        for name in ("prompt_library_system", "prompt_inventory", "prompt_expenses"):
            text = (here / "prompts" / f"{name}.txt").read_text(encoding="utf-8")
            counts[name] = len(command_lines.extract_command_lines(text))
        self.assertEqual(counts, {"prompt_library_system": 15,
                                  "prompt_inventory": 9,
                                  "prompt_expenses": 12})
        for name in ("prompt_60", "prompt_hello_world", "prompt_cli_tool",
                     "prompt_gui"):
            text = (here / "prompts" / f"{name}.txt").read_text(encoding="utf-8")
            self.assertEqual(command_lines.extract_command_lines(text), [])


class AttributionTests(unittest.TestCase):
    def test_double_entity_drops_the_program_like_first(self):
        from kernel.extraction.command_lines import attribute_lines
        self.assertEqual(
            attribute_lines(["expense category add --name"], ["Expense", "Category"]),
            [("category", "add", [("name", True)])])

    def test_program_word_drops_only_with_known_entities(self):
        from kernel.extraction.command_lines import attribute_lines
        self.assertEqual(
            attribute_lines(["library borrow --member-id"], ["Book", "Member"]),
            [("borrow", None, [("member-id", True)])])
        self.assertEqual(
            attribute_lines(["product add --sku"], []),
            [("product", "add", [("sku", True)])])

    def test_sub_first_resolves_through_verb_likeness(self):
        from kernel.extraction.command_lines import attribute_lines
        self.assertEqual(
            attribute_lines(["expense report monthly --month"], ["Expense"]),
            [("expense", "report", [("month", True)])])

    def test_values_and_degenerate_spans_resolve_nothing(self):
        from kernel.extraction.command_lines import attribute_lines
        self.assertEqual(attribute_lines([], ["E"]), [])
        self.assertEqual(attribute_lines([None, ""], ["E"]), [])


class BlockTests(unittest.TestCase):
    def test_lines_are_enumerated_verbatim(self):
        block = prompts.command_lines_block(["a add --x", "b --y"])
        self.assertIn("1. `a add --x`", block)
        self.assertIn("2. `b --y`", block)
        self.assertIn("must appear", block)

    def test_no_lines_means_no_block(self):
        self.assertIsNone(prompts.command_lines_block([]))

    def test_the_block_rides_along_without_disturbing_the_names(self):
        text = prompts.components("req", "NAMES", "EXTRA")
        self.assertIn("NAMES", text)
        self.assertIn("EXTRA", text)
        self.assertIn("req", text)

    def test_components_without_extra_is_unchanged(self):
        text = prompts.components("req", "NAMES")
        self.assertIn("NAMES", text)
        self.assertNotIn("EXTRA", text)


class PipelineWiringTests(unittest.TestCase):
    def test_the_step_hands_each_line_to_the_model(self):
        from kernel.extraction import pipeline
        from kernel.extraction.runner import StepResult

        seen = []

        def fake_generate(llm, prompt, grammar_text, label, temperature=0.0,
                          max_new_tokens=None, seed=None):
            seen.append(prompt)
            return StepResult("components",
                              '{"components": {"facade": {"type": "cli", '
                              '"technology": "none", "invocation": null}, '
                              '"persistence": {"required": false}, '
                              '"crud_services": []}}',
                              10, 1.0, "stop", 3584)

        real_generate = pipeline.runner.generate
        real_assert = pipeline.grammar_check.assert_valid
        pipeline.runner.generate = fake_generate
        pipeline.grammar_check.assert_valid = lambda text, label="grammar": None
        try:
            pipe = pipeline.Pipeline(llm=None, classifier=None, log=_Log())
            pipe._step_components("Run `product add --sku` and `product list`.")
        finally:
            pipeline.runner.generate = real_generate
            pipeline.grammar_check.assert_valid = real_assert
        self.assertEqual(len(seen), 1)
        self.assertIn("1. `product add --sku`", seen[0])
        self.assertIn("2. `product list`", seen[0])

    def test_a_missing_command_is_built_deterministically(self):
        from kernel.extraction import pipeline
        from kernel.extraction.runner import StepResult

        seen = []
        log = _Log()

        def fake_generate(llm, prompt, grammar_text, label, temperature=0.0,
                          max_new_tokens=None, seed=None):
            seen.append(prompt)
            return StepResult("components",
                              '{"components": {"facade": {"type": "cli", '
                              '"technology": "click", "invocation": '
                              '{"commands": [{"name": "book", "options": [], '
                              '"subcommands": []}]}}, '
                              '"persistence": {"required": false}, '
                              '"crud_services": []}}',
                              10, 1.0, "stop", 3584)

        pipe = pipeline.Pipeline(llm=None, classifier=None, log=log)
        pipe.documents[pipeline.DATA_MODELS] = [
            {"name": "Member", "fields": [{"name": "name", "type": "string"}]}]
        real_generate = pipeline.runner.generate
        real_assert = pipeline.grammar_check.assert_valid
        pipeline.runner.generate = fake_generate
        pipeline.grammar_check.assert_valid = lambda text, label="grammar": None
        try:
            pipe._step_components("Run `library member add --name`.")
        finally:
            pipeline.runner.generate = real_generate
            pipeline.grammar_check.assert_valid = real_assert
        self.assertEqual(len(seen), 1, "no model retry needed when built")
        commands = pipe.documents["components"]["facade"]["invocation"]["commands"]
        member = next(c for c in commands if c["name"] == "member")
        subs = {s["name"]: s for s in member["subcommands"]}
        self.assertIn("add", subs)
        self.assertIn("--name", [o["name"] for o in subs["add"]["options"]])

    def test_prose_only_requirements_log_the_fallback(self):
        from kernel.extraction import pipeline
        from kernel.extraction.runner import StepResult

        seen = []
        log = _Log()

        def fake_generate(llm, prompt, grammar_text, label, temperature=0.0,
                          max_new_tokens=None, seed=None):
            seen.append(prompt)
            return StepResult("components",
                              '{"components": {"facade": {"type": "cli", '
                              '"technology": "none", "invocation": null}, '
                              '"persistence": {"required": false}, '
                              '"crud_services": []}}',
                              10, 1.0, "stop", 3584)

        pipe = pipeline.Pipeline(llm=None, classifier=None, log=log)
        pipe.documents[pipeline.DATA_MODELS] = []
        real_generate = pipeline.runner.generate
        real_assert = pipeline.grammar_check.assert_valid
        pipeline.runner.generate = fake_generate
        pipeline.grammar_check.assert_valid = lambda text, label="grammar": None
        try:
            pipe._step_components("Search orders by customer.")
        finally:
            pipeline.runner.generate = real_generate
            pipeline.grammar_check.assert_valid = real_assert
        self.assertEqual(len(seen), 1)
        self.assertNotIn("Go through them one by one", seen[0])
        self.assertTrue(any("no command lines extracted" in line for line in log.lines))

class _Log:
    def __init__(self):
        self.lines = []

    def write(self, message):
        self.lines.append(message)

    def flush(self):
        pass


if __name__ == "__main__":
    unittest.main()
