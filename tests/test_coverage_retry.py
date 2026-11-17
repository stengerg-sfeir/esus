"""A step that omits what an earlier step required is retried once with the miss named.

Why this has tests at all: the prompts already order full coverage ("every
command line must appear", "the operations are a MINIMUM"), but the grammars
cannot enforce presence — omission is always representable — so the misses
reached disk: expenses' surface omits `expense add`, library's omits `member`,
and Category/Budget declare `create` with no create method behind it. The
checker saw each one and the pipeline ignored it.

The generator is stubbed, so the contract is pinned without a model: what is
retried, what is kept, and what is logged. A still-incomplete retry is kept
and declared — better an incomplete document the probe reports than a missing
one — and a clean first attempt is never retried.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import pipeline  # noqa: E402
from kernel.extraction.runner import StepResult  # noqa: E402


def result(payload, truncated=False):
    reason = "length" if truncated else "stop"
    return StepResult("step", json.dumps(payload), 10, 1.0, reason, 3584)


class CollectingLog:
    def __init__(self):
        self.lines = []

    def write(self, message):
        self.lines.append(message)

    def flush(self):
        pass

    def joined(self):
        return "\n".join(self.lines)


def stub_generate(*results):
    """Serve `results` from runner.generate in order; return the prompts seen."""
    prompts_seen = []

    def fake_generate(llm, prompt, grammar_text, label, temperature=0.1,
                      max_new_tokens=None, seed=None):
        prompts_seen.append(prompt)
        return results[len(prompts_seen) - 1]

    real = pipeline.runner.generate
    pipeline.runner.generate = fake_generate
    return prompts_seen, real


class ComponentsRetryTests(unittest.TestCase):
    REQUIREMENTS = (
        "Use `expense add --name` to add and `expense list --from` to list."
    )

    def surface(self, subcommands):
        return {
            "facade": {
                "type": "cli",
                "technology": "click",
                "invocation": {
                    "commands": [
                        {"name": "expense", "subcommands": [
                            {"name": s, "options": [
                                {"name": "--name", "type": "str"},
                                {"name": "--from", "type": "str"}]}
                            for s in subcommands]}
                    ]
                },
            }
        }

    def test_a_surface_missing_a_named_command_is_retried(self):
        log = CollectingLog()
        pipe = pipeline.Pipeline(llm=None, classifier=None, log=log)
        prompts_seen, real = stub_generate(
            result({"components": self.surface(["list"])}),
            result({"components": self.surface(["list", "add"])}),
        )
        try:
            body = pipe._step_components(self.REQUIREMENTS)
        finally:
            pipeline.runner.generate = real
        self.assertEqual(len(prompts_seen), 2, "a surface miss must be retried once")
        self.assertIn("add", {s["name"] for s in body["facade"]["invocation"]["commands"][0]["subcommands"]})
        self.assertIn("retrying once", log.joined())
        self.assertIn("expense add", prompts_seen[1], "the retry names the miss")

    def test_the_retry_carries_the_exact_command_lines(self):
        """The summary names the miss; only the exact lines give the flags."""
        log = CollectingLog()
        pipe = pipeline.Pipeline(llm=None, classifier=None, log=log)
        prompts_seen, real = stub_generate(
            result({"components": self.surface(["list"])}),
            result({"components": self.surface(["list", "add"])}),
        )
        try:
            pipe._step_components(self.REQUIREMENTS)
        finally:
            pipeline.runner.generate = real
        self.assertIn(
            "`expense add --name`", prompts_seen[1],
            "the retry must quote the requirements' own command line",
        )

    def test_a_complete_surface_is_not_retried(self):
        log = CollectingLog()
        pipe = pipeline.Pipeline(llm=None, classifier=None, log=log)
        prompts_seen, real = stub_generate(
            result({"components": self.surface(["list", "add"])}),
        )
        try:
            pipe._step_components(self.REQUIREMENTS)
        finally:
            pipeline.runner.generate = real
        self.assertEqual(len(prompts_seen), 1)
        self.assertNotIn("retrying once", log.joined())

    def test_a_still_incomplete_retry_is_kept_and_declared(self):
        log = CollectingLog()
        pipe = pipeline.Pipeline(llm=None, classifier=None, log=log)
        prompts_seen, real = stub_generate(
            result({"components": self.surface(["list"])}),
            result({"components": self.surface(["list"])}),
        )
        try:
            body = pipe._step_components(self.REQUIREMENTS)
        finally:
            pipeline.runner.generate = real
        self.assertEqual(len(prompts_seen), 2)
        self.assertIsNotNone(body, "an incomplete document beats a missing one")
        self.assertIn("probe will report", log.joined())


class ContractsRetryTests(unittest.TestCase):
    def contracts(self, methods):
        return [
            {
                "service_name": "CategoryRepository",
                "methods": [{"name": name} for name in methods],
            }
        ]

    def pipe_with_domain(self, log):
        pipe = pipeline.Pipeline(llm=None, classifier=None, log=log)
        pipe.documents[pipeline.DATA_MODELS] = [
            {"name": "Category", "fields": [{"name": "id"}]}
        ]
        pipe.documents[pipeline.COMPONENTS] = {
            "crud_services": [
                {"entity": "Category", "operations": ["create", "delete"]}
            ]
        }
        return pipe

    def test_a_contract_missing_a_required_operation_is_retried(self):
        log = CollectingLog()
        pipe = self.pipe_with_domain(log)
        prompts_seen, real = stub_generate(
            result({"service_contracts": self.contracts(["delete_category"])}),
            result({"service_contracts": self.contracts(["delete_category", "create_category"])}),
        )
        try:
            pipe._step_contracts("requirements")
        finally:
            pipeline.runner.generate = real
        self.assertEqual(len(prompts_seen), 2, "a crud miss must be retried once")
        names = {m["name"] for m in pipe.documents["service_contracts"][0]["methods"]}
        self.assertIn("create_category", names)
        self.assertIn("retrying once", log.joined())
        self.assertIn("create", prompts_seen[1], "the retry names the miss")

    def test_a_complete_contract_is_not_retried(self):
        log = CollectingLog()
        pipe = self.pipe_with_domain(log)
        prompts_seen, real = stub_generate(
            result({"service_contracts": self.contracts(["delete_category", "create_category"])}),
        )
        try:
            pipe._step_contracts("requirements")
        finally:
            pipeline.runner.generate = real
        self.assertEqual(len(prompts_seen), 1)
        self.assertNotIn("retrying once", log.joined())


class ComponentsFlagRetryTests(unittest.TestCase):
    """A verb the surface declares with none of its data flags is retried.

    Inventory's `product add` carried only `-help`/`-version` while the
    requirements pass `--sku`: the verb check passes and the path is still
    stranded. The retry names the missing flag, with the exact command line.
    """

    REQUIREMENTS = "Run `product add --sku --name`."

    def surface(self, options):
        return {
            "facade": {
                "type": "cli",
                "technology": "click",
                "invocation": {
                    "commands": [
                        {"name": "product", "subcommands": [
                            {"name": "add", "options": [
                                {"name": name, "type": "str"} for name in options]}]}
                    ]
                },
            }
        }

    def test_a_verb_missing_its_flags_is_retried(self):
        log = CollectingLog()
        pipe = pipeline.Pipeline(llm=None, classifier=None, log=log)
        prompts_seen, real = stub_generate(
            result({"components": self.surface(["--name"])}),
            result({"components": self.surface(["--sku", "--name"])}),
        )
        try:
            body = pipe._step_components(self.REQUIREMENTS)
        finally:
            pipeline.runner.generate = real
        self.assertEqual(len(prompts_seen), 2, "a flag miss must be retried once")
        subs = body["facade"]["invocation"]["commands"][0]["subcommands"]
        self.assertIn("--sku", {o["name"] for o in subs[0]["options"]})
        self.assertIn("retrying once", log.joined())
        self.assertIn("--sku", prompts_seen[1], "the retry names the missing flag")

    def test_a_flag_complete_surface_is_not_retried(self):
        log = CollectingLog()
        pipe = pipeline.Pipeline(llm=None, classifier=None, log=log)
        prompts_seen, real = stub_generate(
            result({"components": self.surface(["--sku", "--name"])}),
        )
        try:
            pipe._step_components(self.REQUIREMENTS)
        finally:
            pipeline.runner.generate = real
        self.assertEqual(len(prompts_seen), 1)
        self.assertNotIn("retrying once", log.joined())


class AdaptersModelRetryTests(unittest.TestCase):
    """An adapter assembling an undeclared model field is retried.

    `author_id` into a `Book` with no such field fails at construction no
    matter what the CLI supplies. The retry names the field and its entity;
    the deterministic repairs run again on the second attempt.
    """

    def pipe_with_contracts(self, log):
        pipe = pipeline.Pipeline(llm=None, classifier=None, log=log)
        pipe.documents[pipeline.DATA_MODELS] = [
            {"name": "Book", "fields": [{"name": "title", "type": "string"}]}
        ]
        pipe.documents[pipeline.SERVICE_CONTRACTS] = [
            {"service_name": "BookRepository", "methods": [
                {"name": "create_book",
                 "params": [{"name": "book", "type": "Book"}]}]}
        ]
        return pipe

    def adapters(self, fields):
        return [{
            "action_name": "add_book",
            "target_service": "BookRepository",
            "target_method": "create_book",
            "input_fields": [
                {"field_name": name, "target_param": "book",
                 "transform": "DIRECT", "lookup_entity": None, "required": True}
                for name in fields],
        }]

    def test_an_adapter_assembling_an_undeclared_field_is_retried(self):
        log = CollectingLog()
        pipe = self.pipe_with_contracts(log)
        prompts_seen, real = stub_generate(
            result({"interaction_adapters": self.adapters(["title", "author_id"])}),
            result({"interaction_adapters": self.adapters(["title"])}),
        )
        try:
            pipe._step_adapters("requirements")
        finally:
            pipeline.runner.generate = real
        self.assertEqual(len(prompts_seen), 2, "a model miss must be retried once")
        fields = pipe.documents["interaction_adapters"][0]["input_fields"]
        self.assertEqual([f["field_name"] for f in fields], ["title"])
        self.assertIn("retrying once", log.joined())
        self.assertIn("author_id", prompts_seen[1], "the retry names the field")

    def test_a_clean_adapter_is_not_retried(self):
        log = CollectingLog()
        pipe = self.pipe_with_contracts(log)
        prompts_seen, real = stub_generate(
            result({"interaction_adapters": self.adapters(["title"])}),
        )
        try:
            pipe._step_adapters("requirements")
        finally:
            pipeline.runner.generate = real
        self.assertEqual(len(prompts_seen), 1)
        self.assertNotIn("retrying once", log.joined())


@mock.patch.object(pipeline, "MECHANICAL_ADAPTERS", False)
class AdaptersFlagRetryTests(unittest.TestCase):
    """A required field no bound leaf flag supplies is retried.

    `file_path` where the leaf offers `--output` is adapter-side: renaming
    the field to the flag heals it without touching the surface. Surface-side
    misses (a flag the requirements name and no leaf declares) are step D's
    retry; this fires when the adapter side can move.
    """

    REQUIREMENTS = "Run `store export --output`."

    def pipe_with_service(self, log, options):
        pipe = pipeline.Pipeline(llm=None, classifier=None, log=log)
        pipe.documents[pipeline.DATA_MODELS] = []
        pipe.documents[pipeline.SERVICE_CONTRACTS] = [
            {"service_name": "StoreService", "methods": [
                {"name": "export_data",
                 "params": [{"name": "file_path", "type": "str"}]}]}
        ]
        pipe.documents[pipeline.COMPONENTS] = {
            "facade": {"type": "cli", "technology": "argparse",
                       "invocation": {"commands": [
                           {"name": "store", "options": [],
                            "subcommands": [
                                {"name": "export", "options": [
                                    {"name": name, "type": "str"} for name in options]}]}]}}
        }
        return pipe

    def adapters(self, fields):
        return [{
            "action_name": "export_data",
            "target_service": "StoreService",
            "target_method": "export_data",
            "input_fields": [
                {"field_name": name, "target_param": "file_path",
                 "transform": "DIRECT", "lookup_entity": None, "required": True}
                for name in fields],
        }]

    def test_a_field_no_leaf_flag_supplies_is_retried(self):
        log = CollectingLog()
        pipe = self.pipe_with_service(log, ["--output"])
        prompts_seen, real = stub_generate(
            result({"interaction_adapters": self.adapters(["file_path"])}),
            result({"interaction_adapters": self.adapters(["output"])}),
        )
        try:
            pipe._step_adapters(self.REQUIREMENTS)
        finally:
            pipeline.runner.generate = real
        self.assertEqual(len(prompts_seen), 2, "an unreachable field must be retried once")
        fields = pipe.documents["interaction_adapters"][0]["input_fields"]
        self.assertEqual([f["field_name"] for f in fields], ["output"])
        self.assertIn("retrying once", log.joined())
        self.assertIn("file_path", prompts_seen[1], "the retry names the field")

    def test_a_suppliable_field_is_not_retried(self):
        log = CollectingLog()
        pipe = self.pipe_with_service(log, ["--output"])
        prompts_seen, real = stub_generate(
            result({"interaction_adapters": self.adapters(["output"])}),
        )
        try:
            pipe._step_adapters(self.REQUIREMENTS)
        finally:
            pipeline.runner.generate = real
        self.assertEqual(len(prompts_seen), 1)
        self.assertNotIn("retrying once", log.joined())


class DeterministicSamplingTests(unittest.TestCase):
    """Same prompt, same document: temperature 0 plus a fixed seed.

    Reproducibility is diagnostic, not corrective — a systematic miss repeats
    faithfully, which is what makes it debuggable. Coverage retries keep the
    cold temperature: re-asking wants the same mind, not a hotter one.
    """

    def setUp(self):
        from kernel.extraction import grammar_check
        self._real_assert_valid = grammar_check.assert_valid
        grammar_check.assert_valid = lambda text, label="grammar": None

    def tearDown(self):
        from kernel.extraction import grammar_check
        grammar_check.assert_valid = self._real_assert_valid

    def calls_with(self, *results):
        seen = []

        def fake_generate(llm, prompt, grammar_text, label, temperature=0.1,
                          max_new_tokens=None, seed=None):
            seen.append({"temperature": temperature, "seed": seed})
            return results[len(seen) - 1]

        real = pipeline.runner.generate
        pipeline.runner.generate = fake_generate
        self.addCleanup(lambda: setattr(pipeline.runner, "generate", real))
        return seen

    def test_first_attempts_use_temperature_zero_and_the_fixed_seed(self):
        from kernel.extraction import pipeline as pipeline_module
        log = CollectingLog()
        pipe = pipeline.Pipeline(llm=None, classifier=None, log=log)
        seen = self.calls_with(result({"widgets": [1, 2]}))
        pipe._generate("widgets", "prompt", "grammar")
        self.assertEqual(
            seen, [{"temperature": pipeline_module.TEMPERATURE, "seed": pipeline_module.SEED}])
        self.assertEqual(pipeline_module.TEMPERATURE, 0.0)

    def test_a_coverage_retry_is_cold_then_hot_on_parse_failure(self):
        """Cold re-ask, hot escape hatch — every call seeded.

        The coverage retry re-asks at temperature 0 (reproducible); only a
        retry attempt that fails to parse escalates to 0.35, the same ladder
        as any other step. A retry that healed would do so deterministically
        first, and only then by exploration.
        """
        from kernel.extraction import pipeline as pipeline_module
        log = CollectingLog()
        pipe = pipeline.Pipeline(llm=None, classifier=None, log=log)
        pipe.documents[pipeline.DATA_MODELS] = [
            {"name": "Category", "fields": [{"name": "id"}]}
        ]
        pipe.documents[pipeline.COMPONENTS] = {
            "crud_services": [{"entity": "Category", "operations": ["create"]}]
        }
        missing = result({"service_contracts": [
            {"service_name": "CategoryRepository", "methods": [
                {"name": "delete_category"}]}]})
        garbage = result("not json")
        fixed = result({"service_contracts": [
            {"service_name": "CategoryRepository", "methods": [
                {"name": "create_category"}]}]})
        seen = self.calls_with(missing, garbage, fixed)
        pipe._step_contracts("requirements")
        self.assertEqual(
            [call["temperature"] for call in seen],
            [pipeline_module.TEMPERATURE, pipeline_module.TEMPERATURE,
             pipeline_module.RETRY_TEMPERATURE])
        self.assertTrue(all(call["seed"] == pipeline_module.SEED for call in seen))


class KeepBestRetryTests(unittest.TestCase):
    """A degrading retry must not replace good content.

    Expenses' adapters came back from coverage retry as a one-action
    fragment: same miss count, twenty-six actions lost, and the fragment was
    kept. Fewer misses wins; ties and unusable retries keep the incumbent,
    and the outcome names both counts.
    """

    def test_fewer_misses_keeps_the_retry(self):
        from kernel.extraction.pipeline import _settle_retry
        log = CollectingLog()
        body, misses = _settle_retry("widgets", "first", ["a"], "second", [],
                                     log, unit="widget(s)")
        self.assertEqual((body, misses), ("second", []))
        self.assertIn("healed 1->0", log.joined())

    def test_a_tie_keeps_the_first_attempt(self):
        from kernel.extraction.pipeline import _settle_retry
        log = CollectingLog()
        body, misses = _settle_retry("widgets", "first", ["a"], "second", ["b"],
                                     log, unit="widget(s)")
        self.assertEqual((body, misses), ("first", ["a"]))
        self.assertIn("kept first attempt", log.joined())

    def test_more_misses_keeps_the_first_attempt(self):
        from kernel.extraction.pipeline import _settle_retry
        log = CollectingLog()
        body, _ = _settle_retry("widgets", "first", ["a"], "second", ["b", "c"],
                                log, unit="widget(s)")
        self.assertEqual(body, "first")

    def test_an_unusable_retry_keeps_the_first_attempt(self):
        from kernel.extraction import pipeline as pipeline_module
        log = CollectingLog()
        first = {"components": "first"}
        pipe = pipeline_module.Pipeline(llm=None, classifier=None, log=log)
        pipe.documents[pipeline_module.COMPONENTS] = first
        body, _ = pipeline_module._settle_retry(
            "components", first, ["a"], None, [], log)
        self.assertIs(body, first)

    def test_a_degrading_components_retry_keeps_the_first_document(self):
        log = CollectingLog()
        pipe = pipeline.Pipeline(llm=None, classifier=None, log=log)
        first_surface = {
            "facade": {
                "type": "cli",
                "technology": "click",
                "invocation": {
                    "commands": [
                        {
                            "name": "product",
                            "subcommands": [
                                {
                                    "name": "add",
                                    "options": [{"name": "--name", "type": "str"}],
                                }
                            ],
                        },
                        {
                            "name": "budget",
                            "subcommands": [
                                {
                                    "name": "add",
                                    "options": [{"name": "--x", "type": "str"}],
                                }
                            ],
                        },
                    ]
                },
            }
        }
        degraded = {
            "facade": {
                "type": "cli",
                "technology": "click",
                "invocation": {
                    "commands": [
                        {
                            "name": "product",
                            "subcommands": [
                                {
                                    "name": "add",
                                    "options": [{"name": "--name", "type": "str"}],
                                }
                            ],
                        }
                    ]
                },
            }
        }
        prompts_seen, real = stub_generate(
            result({"components": first_surface}),
            result({"components": degraded}),
        )
        requirements = (
            "Run `product add --sku --name`, `budget add --x`, `budget list --y`."
        )
        try:
            pipe._step_components(requirements)
        finally:
            pipeline.runner.generate = real
        self.assertEqual(len(prompts_seen), 2)
        kept = pipe.documents["components"]
        names = {c["name"] for c in kept["facade"]["invocation"]["commands"]}
        self.assertEqual(names, {"product", "budget"})
        self.assertIn("kept first attempt", log.joined())

if __name__ == "__main__":
    unittest.main()
