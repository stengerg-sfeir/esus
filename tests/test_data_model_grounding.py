"""Step B's grounding: the criterion it applies, and the phrases it is shown.

Step B (`data_models`) is the only step nothing constrains — every other step's
grammar is generated from the names an earlier step produced, so it cannot invent
one, but step A emits prose and prose cannot become a vocabulary. B therefore ran
on the raw requirements with an open grammar, and for a program that models
nothing it filled the required shape from priors: `cli_tool`, a CSV-to-JSON
converter, invented `users, products, orders, order_items`.

These tests pin the two halves of the fix:

- the prompt states a **criterion** (a thing the program keeps and looks up) not a
  list of verbs — the old wording named "computes, prints, parses or transforms",
  which describes cli_tool exactly, and cli_tool invented anyway;
- step A's phrases are **shown** to B as grounding, with an explicit warning that
  a use case, service or repository named there is not an entity.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import prompts  # noqa: E402


class IntentionsBlockTests(unittest.TestCase):
    def test_phrases_are_listed(self):
        block = prompts.intentions_block(
            ["Track expenses by category", "Report monthly totals"]
        )
        self.assertIn("- Track expenses by category", block)
        self.assertIn("- Report monthly totals", block)

    def test_the_block_warns_against_turning_use_cases_into_entities(self):
        """Step A's phrases name services and repositories too."""
        block = prompts.intentions_block(["Create a Repository for Expense"])
        self.assertIn("NOT a data model", block)
        self.assertIn("repository", block.lower())

    def test_no_phrases_yields_no_block(self):
        """An empty list must not become an empty heading."""
        for empty in ([], None, [""], ["   "], [None, 3]):
            self.assertIsNone(prompts.intentions_block(empty), empty)

    def test_blank_entries_are_dropped_but_real_ones_kept(self):
        block = prompts.intentions_block(["  ", "Keep the budgets  ", None])
        self.assertIn("- Keep the budgets", block)
        self.assertNotIn("- None", block)

    def test_the_block_reaches_the_step_b_prompt(self):
        block = prompts.intentions_block(["Store each Expense"])
        prompt = prompts.data_models("requirements text", block)
        self.assertIn("Store each Expense", prompt)
        self.assertIn(prompts.DATA_MODELS_SYSTEM, prompt)

    def test_without_a_block_the_prompt_still_builds(self):
        """A run whose step A failed must still extract, only ungrounded."""
        prompt = prompts.data_models("requirements text")
        self.assertIn(prompts.DATA_MODELS_SYSTEM, prompt)
        self.assertIn("requirements text", prompt)


class CriterionTests(unittest.TestCase):
    """The prompt must state a criterion, not a permission or a verb list."""

    def test_the_criterion_is_about_keeping_and_looking_up(self):
        system = prompts.DATA_MODELS_SYSTEM
        self.assertIn("KEEPS", system)
        self.assertIn("looks it up by an identifier", system)

    def test_pass_through_data_is_named_as_not_an_entity(self):
        """The exact case cli_tool is: parsed and re-emitted, transformed on."""
        system = prompts.DATA_MODELS_SYSTEM
        self.assertIn("parsed and re-emitted", system)
        self.assertIn("transformed and passed on", system)

    def test_grounding_in_the_requirements_words_is_required(self):
        """Stated so a translated name is still grounded, not string-matched."""
        system = prompts.DATA_MODELS_SYSTEM
        self.assertIn("in whatever language they are written", system)

    def test_the_empty_answer_stays_permitted(self):
        """It was already legal — hello emits it — and must remain so."""
        self.assertIn('{"data_models": []}', prompts.DATA_MODELS_SYSTEM)


if __name__ == "__main__":
    unittest.main(verbosity=2)
