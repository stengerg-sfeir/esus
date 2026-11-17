"""Field aliases: asserted once by a human, honored deterministically after.

Applying renames the recorded field (its target never moves); stale pairs,
predated prompts and name collisions are skipped visibly rather than
applied. The review flow is pinned without a human: numbered suggestions,
free-text flags and skips all record exactly what was answered.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import aliases  # noqa: E402
from kernel.extraction.decisions import requirements_sha  # noqa: E402
from review_aliases import ask, run_review, suggest_flags  # noqa: E402


def adapters():
    return [{"action_name": "export", "target_service": "S",
             "target_method": "export_data",
             "input_fields": [
                 {"field_name": "file_path", "target_param": "file_path",
                  "transform": "DIRECT", "required": True},
                 {"field_name": "start_date", "target_param": "start_date",
                  "transform": "DIRECT", "required": False}]}]


class Log:
    def __init__(self):
        self.lines = []

    def write(self, text):
        self.lines.append(text)


class ApplyAliasesTests(unittest.TestCase):
    RECORD = {"action": "export", "field": "file_path", "flag": "output",
              "requirements_sha": requirements_sha("x")}

    def test_a_matching_record_renames_the_field_only(self):
        docs = adapters()
        aliases.apply_aliases(docs, [dict(self.RECORD)], Log(), requirements_text="x")
        field = docs[0]["input_fields"][0]
        self.assertEqual(field["field_name"], "output")
        self.assertEqual(field["target_param"], "file_path")

    def test_a_stale_pair_applies_to_nothing(self):
        docs = adapters()
        log = Log()
        aliases.apply_aliases(
            docs, [{"action": "gone", "field": "file_path", "flag": "output"}],
            log, requirements_text="x")
        self.assertEqual(docs[0]["input_fields"][0]["field_name"], "file_path")
        self.assertEqual(log.lines, [])

    def test_a_collision_is_skipped_loudly(self):
        docs = adapters()
        docs[0]["input_fields"].append(
            {"field_name": "output", "target_param": "other",
             "transform": "DIRECT", "required": False})
        log = Log()
        aliases.apply_aliases(docs, [dict(self.RECORD)], log, requirements_text="x")
        self.assertEqual(docs[0]["input_fields"][0]["field_name"], "file_path")
        self.assertTrue(any("collides" in line for line in log.lines))

    def test_a_predated_prompt_drops_the_record(self):
        docs = adapters()
        log = Log()
        stamped = {"action": "export", "field": "file_path", "flag": "output",
                   "requirements_sha": aliases.requirements_sha("old prompt")}
        aliases.apply_aliases(docs, [stamped], log,
                              requirements_text="different prompt")
        self.assertEqual(docs[0]["input_fields"][0]["field_name"], "file_path")
        self.assertTrue(any("predates a prompt change" in line for line in log.lines))

    def test_a_legacy_record_without_a_stamp_applies(self):
        docs = adapters()
        legacy = {"action": "export", "field": "file_path", "flag": "output"}
        aliases.apply_aliases(docs, [legacy], Log(), requirements_text="anything")
        self.assertEqual(docs[0]["input_fields"][0]["field_name"], "output")


class CreateRecordRoutingTests(unittest.TestCase):
    """Creation records are not renames: the adapter field keeps its name.

    A record carrying a `create` spec asserts a model field exists (owned by
    apply_model_fields), not that the adapter field should move. Routing it
    through the rename reported a collision of the field against itself —
    noise that read like a defect in the run log.
    """

    def adapters(self):
        return [{"action_name": "add_book", "target_service": "R",
                 "target_method": "m",
                 "input_fields": [
                     {"field_name": "author_id", "target_param": "book",
                      "transform": "DIRECT", "required": True}]}]

    def test_a_create_record_leaves_the_adapter_untouched_silently(self):
        log = Log()
        record = {"action": "add_book", "field": "author_id",
                  "flag": "author_id",
                  "create": {"entity": "Book", "name": "author_id"}}
        docs = self.adapters()
        aliases.apply_aliases(docs, [record], log, requirements_text="x")
        self.assertEqual(docs[0]["input_fields"][0]["field_name"], "author_id")
        self.assertEqual(log.lines, [])

    def test_a_same_name_rename_is_a_silent_no_op(self):
        log = Log()
        record = {"action": "add_book", "field": "author_id",
                  "flag": "author_id"}
        docs = self.adapters()
        aliases.apply_aliases(docs, [record], log, requirements_text="x")
        self.assertEqual(docs[0]["input_fields"][0]["field_name"], "author_id")
        self.assertEqual(log.lines, [])


class SuggestFlagsTests(unittest.TestCase):
    def test_containment_outranks_similarity(self):
        self.assertEqual(
            suggest_flags(["from-date", "output", "method"], "start_date"),
            ["from-date"])

    def test_no_resemblance_means_no_suggestions(self):
        self.assertEqual(suggest_flags(["aaa", "bbb"], "file_path"), [])

    def test_suggestions_are_deterministic(self):
        first = suggest_flags(["amount", "count", "total"], "amount_cents")
        self.assertEqual(first, suggest_flags(["total", "amount", "count"], "amount_cents"))


class AskTests(unittest.TestCase):
    QUESTION = {"action": "a", "field": "f", "suggestions": ["output", "file"]}

    def test_a_number_takes_the_suggestion(self):
        self.assertEqual(ask(self.QUESTION, lambda _: "2"), ("rename", "file"))

    def test_free_text_is_stripped_of_dashes(self):
        self.assertEqual(ask(self.QUESTION, lambda _: "--output"), ("rename", "output"))

    def test_a_number_past_the_suggestions_takes_the_create_offer(self):
        question = dict(self.QUESTION, create={"name": "f", "entity": "E"})
        self.assertEqual(ask(question, lambda _: "3")[0], "create")

    def test_free_text_never_creates_even_matching_the_offer(self):
        """Creation changes the schema: only an explicit number may do it."""
        question = dict(self.QUESTION, create={"name": "author_id", "entity": "E"},
                        suggestions=[])
        self.assertEqual(ask(question, lambda _: "author_id"), ("rename", "author_id"))

    def test_skip_and_garbage_answer_nothing(self):
        self.assertEqual(ask(self.QUESTION, lambda _: "skip"), (None, None))
        self.assertEqual(ask(self.QUESTION, lambda _: "9"), (None, None))


def writes(directory, adapters, requirements="req", export_options=None):
    """The review fixture: `store export` offers `--output` unless told otherwise.

    Free text is legitimate only when the flag exists to take the spelling —
    renaming onto a flagless leaf heals nothing — so the default leaf declares
    `--output` (unbound to any field, hence still uncovered and askable).
    Pass `export_options=[]` for the flagless shape, which the review skips.
    """
    if export_options is None:
        export_options = [{"name": "--output", "type": "str"}]
    path = Path(directory)
    (path / "interaction_adapters.json").write_text(
        json.dumps({"interaction_adapters": adapters}), encoding="utf-8")
    (path / "requirements.txt").write_text(requirements, encoding="utf-8")
    components = {"facade": {"type": "cli", "technology": "argparse",
                             "invocation": {"commands": [
                                 {"name": "store", "options": [],
                                  "subcommands": [
                                      {"name": "export",
                                       "options": export_options}]}]}}}
    (path / "components.json").write_text(
        json.dumps({"components": components}), encoding="utf-8")
    for name in ("service_contracts", "data_models", "pattern_matches"):
        (path / f"{name}.json").write_text(json.dumps({name: []}),
                                           encoding="utf-8")


class ReviewFlowTests(unittest.TestCase):
    def test_answers_are_recorded_stamped_and_patched(self):
        with tempfile.TemporaryDirectory() as directory:
            writes(directory, adapters())
            asked, answered = run_review(
                directory, input_fn=lambda _: "output", out_fn=lambda _: None)
            self.assertEqual((asked, answered), (1, 1))
            saved = aliases.load_aliases(directory)
            self.assertEqual(len(saved), 1)
            self.assertEqual(
                (saved[0]["action"], saved[0]["field"], saved[0]["flag"]),
                ("export", "file_path", "output"))
            self.assertIn("requirements_sha", saved[0])
            patched = json.loads(
                (Path(directory) / "interaction_adapters.json").read_text(encoding="utf-8"))
            self.assertEqual(
                patched["interaction_adapters"][0]["input_fields"][0]["field_name"],
                "output")

    def test_skip_leaves_everything_open(self):
        with tempfile.TemporaryDirectory() as directory:
            writes(directory, adapters())
            asked, answered = run_review(
                directory, input_fn=lambda _: "skip", out_fn=lambda _: None)
            self.assertEqual((asked, answered), (1, 0))
            self.assertEqual(aliases.load_aliases(directory), [])

    def test_a_second_run_finds_nothing_open(self):
        with tempfile.TemporaryDirectory() as directory:
            writes(directory, adapters())
            run_review(directory, input_fn=lambda _: "output", out_fn=lambda _: None)
            asked, answered = run_review(
                directory, input_fn=lambda _: "output", out_fn=lambda _: None)
            self.assertEqual((asked, answered), (0, 0))

    def test_a_flagless_leaf_is_not_asked(self):
        """The expenses shape: no data flag, no suggestion, no possible answer.

        `store export` declares nothing, so renaming `file_path` to a typed-in
        name could bind nothing — the defect is surface (missing flags on the
        leaf), owned by rerun/repair with the probe still reporting it. The
        review asks nothing instead of posing an impossible choice.
        """
        from review_aliases import collect_questions
        with tempfile.TemporaryDirectory() as directory:
            writes(directory, adapters(), export_options=[])
            questions, _ = collect_questions(directory)
            self.assertEqual(questions, [])

    def test_flag_footer_promises_no_model_field(self):
        from review_aliases import collect_questions, describe_question
        with tempfile.TemporaryDirectory() as directory:
            writes(directory, adapters())
            questions, _ = collect_questions(directory)
            self.assertEqual(len(questions), 1)
            text = "\n".join(describe_question(1, 1, questions[0]))
            self.assertIn("renames the adapter field to the flag's spelling", text)
            self.assertNotIn("creates the model field", text)


class ModelFallbackTests(unittest.TestCase):
    """No resembling flag: the entity's own fields are offered instead."""

    def test_model_fields_containing_the_name_are_suggested(self):
        from review_aliases import suggest_model_fields
        models = {"Book": ["title", "available_copies", "isbn"]}
        self.assertEqual(
            suggest_model_fields(models, "Book", "copies"), ["available_copies"])
        self.assertEqual(suggest_model_fields(models, "Book", "zzz"), [])
        self.assertEqual(suggest_model_fields(models, "Nope", "copies"), [])
        self.assertEqual(suggest_model_fields({}, "Book", "copies"), [])

    def test_empty_suggestions_come_with_guidance(self):
        from review_aliases import describe_question
        lines = describe_question(1, 1, {
            "action": "add_book", "field": "copies", "target": "book",
            "transform": "DIRECT", "entity": "Book", "kind": "model",
            "leaves": ["book add"], "flags": ["copies"], "suggestions": [],
            "problem": ["Book declares no 'copies' field, so building it fails."],
            "supplied": [("book add", "--copies")], "leaf_flags": ["--copies"],
            "question": "Which Book field does this value fill?",
            "service": "BookRepo", "method": "create_book", "spellings": {}})
        text = "\n".join(lines)
        self.assertIn("ADAPTER 'add_book' feeds CLI input into BookRepo.create_book.", text)
        self.assertIn("Problem: Book declares no 'copies' field", text)
        self.assertIn("arrives via flag '--copies' on 'book add'", text)
        self.assertIn("Which Book field does this value fill?", text)
        self.assertIn("renames the adapter field, or creates the model field", text)

    def test_answering_the_unchanged_name_records_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "interaction_adapters.json").write_text(json.dumps(
                {"interaction_adapters": [{
                    "action_name": "add_book", "target_service": "BookRepo",
                    "target_method": "create_book",
                    "input_fields": [
                        {"field_name": "copies", "target_param": "book",
                         "transform": "DIRECT", "required": True}]}]}),
                encoding="utf-8")
            (path / "service_contracts.json").write_text(json.dumps(
                {"service_contracts": [{
                    "service_name": "BookRepo", "methods": [
                        {"name": "create_book",
                         "params": [{"name": "book", "type": "Book"}]}]}]}),
                encoding="utf-8")
            (path / "data_models.json").write_text(json.dumps(
                {"data_models": [{
                    "name": "Book", "fields": [
                        {"name": "available_copies", "type": "int"}]}]}),
                encoding="utf-8")
            (path / "components.json").write_text(json.dumps(
                {"components": {
                    "facade": {"type": "cli", "technology": "argparse",
                               "invocation": {"commands": [
                                   {"name": "book", "options": [],
                                    "subcommands": [
                                        {"name": "add", "options": [
                                            {"name": "--copies", "type": "int"}]}]}]}}}}),
                encoding="utf-8")
            (path / "requirements.txt").write_text("req", encoding="utf-8")
            for name in ("errors", "pattern_matches", "intentions", "invariants"):
                (path / f"{name}.json").write_text(json.dumps({name: []}),
                                                   encoding="utf-8")
            said = []
            asked, answered = run_review(
                directory, input_fn=lambda _: "copies",
                out_fn=said.append)
            self.assertEqual((asked, answered), (1, 0))
            self.assertTrue(any("changes nothing" in line for line in said))
            from kernel.extraction import aliases as _aliases
            self.assertEqual(_aliases.load_aliases(directory), [])

    def test_answering_a_model_field_records_and_patches(self):
        from kernel.extraction import aliases as _aliases
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "interaction_adapters.json").write_text(json.dumps(
                {"interaction_adapters": [{
                    "action_name": "add_book", "target_service": "BookRepo",
                    "target_method": "create_book",
                    "input_fields": [
                        {"field_name": "copies", "target_param": "book",
                         "transform": "DIRECT", "required": True}]}]}),
                encoding="utf-8")
            (path / "service_contracts.json").write_text(json.dumps(
                {"service_contracts": [{
                    "service_name": "BookRepo", "methods": [
                        {"name": "create_book",
                         "params": [{"name": "book", "type": "Book"}]}]}]}),
                encoding="utf-8")
            (path / "data_models.json").write_text(json.dumps(
                {"data_models": [{
                    "name": "Book", "fields": [
                        {"name": "available_copies", "type": "int"}]}]}),
                encoding="utf-8")
            (path / "components.json").write_text(json.dumps(
                {"components": {
                    "facade": {"type": "cli", "technology": "argparse",
                               "invocation": {"commands": [
                                   {"name": "book", "options": [],
                                    "subcommands": [
                                        {"name": "add", "options": [
                                            {"name": "--copies", "type": "int"}]}]}]}}}}),
                encoding="utf-8")
            (path / "requirements.txt").write_text("req", encoding="utf-8")
            for name in ("errors", "pattern_matches", "intentions", "invariants"):
                (path / f"{name}.json").write_text(json.dumps({name: []}),
                                                   encoding="utf-8")
            asked, answered = run_review(
                directory, input_fn=lambda _: "available_copies",
                out_fn=lambda _: None)
            self.assertEqual((asked, answered), (1, 1))
            patched = json.loads(
                (path / "interaction_adapters.json").read_text(encoding="utf-8"))
            fields = patched["interaction_adapters"][0]["input_fields"]
            self.assertEqual(fields[0]["field_name"], "available_copies")
            self.assertEqual(fields[0]["target_param"], "book")


class ModelFallbackDirectionTests(unittest.TestCase):
    """The model fallback suggests abbreviations, never shared suffixes.

    Offering `id` for `author_id` would invite repointing an author
    reference at the record itself — the same corruption the rename repair
    refuses. The fallback that produced it is fixed here, not just the
    repair that acted on it.
    """

    def test_reverse_containment_is_never_suggested(self):
        from review_aliases import suggest_model_fields
        models = {"Book": ["id", "title", "available_copies"]}
        self.assertEqual(suggest_model_fields(models, "Book", "author_id"), [])
        self.assertEqual(
            suggest_model_fields(models, "Book", "copies"), ["available_copies"])


class InferNewFieldTests(unittest.TestCase):
    """A created field needs every piece derived, or no offer at all."""

    def test_flag_type_plus_lookup_resolves_everything(self):
        from review_aliases import infer_new_field
        entry = {"target_param": "book", "transform": "LOOKUP_ID",
                 "lookup_entity": "Author", "required": True}
        supplied = [("book add", "--author-id", "int")]
        models = {"Book": ["title"], "Author": ["id"]}
        pk_of = {"Author": "id"}
        self.assertEqual(
            infer_new_field(entry, supplied, pk_of, models, "Book", "author_id"),
            {"entity": "Book", "name": "author_id", "type": "int",
             "nullable": False, "unique": False,
             "foreign_key": {"target_entity": "Author", "target_field": "id",
                             "relationship": "many_to_one"},
             "status": "deduced",
             "provenance": "flag '--author-id' : int"})

    def test_lookup_alone_defaults_to_int_without_a_foreign_key(self):
        from review_aliases import infer_new_field
        entry = {"target_param": "x", "transform": "LOOKUP_ID",
                 "lookup_entity": None, "required": False}
        spec = infer_new_field(entry, [], {}, {"E": []}, "E", "thing_id")
        self.assertEqual((spec["type"], spec["nullable"], spec["foreign_key"]),
                         ("int", True, None))

    def test_untyped_direct_without_a_flag_is_unofferable(self):
        from review_aliases import infer_new_field
        entry = {"target_param": "x", "transform": "DIRECT", "required": True}
        self.assertIsNone(infer_new_field(entry, [], {}, {"E": []}, "E", "thing"))

    def test_an_existing_field_is_never_created(self):
        from review_aliases import infer_new_field
        entry = {"target_param": "x", "transform": "LOOKUP_ID", "required": True}
        models = {"E": ["thing_id"]}
        self.assertIsNone(infer_new_field(entry, [], {}, models, "E", "thing_id"))

    def test_a_list_flag_is_never_a_model_type(self):
        from review_aliases import infer_new_field
        entry = {"target_param": "x", "transform": "DIRECT", "required": True}
        supplied = [("leaf", "--tags", "list")]
        self.assertIsNone(
            infer_new_field(entry, supplied, {}, {"E": []}, "E", "tags"))


class CreateFlowTests(unittest.TestCase):
    """Answering the create offer writes the model, records the spec."""

    def setup_dir(self, directory):
        path = Path(directory)
        (path / "interaction_adapters.json").write_text(json.dumps(
            {"interaction_adapters": [{
                "action_name": "add_book", "target_service": "BookRepo",
                "target_method": "create_book",
                "input_fields": [
                    {"field_name": "author_id", "target_param": "book",
                     "transform": "LOOKUP_ID", "lookup_entity": "Author",
                     "required": True}]}]}), encoding="utf-8")
        (path / "service_contracts.json").write_text(json.dumps(
            {"service_contracts": [{
                "service_name": "BookRepo", "methods": [
                    {"name": "create_book",
                     "params": [{"name": "book", "type": "Book"}]}]}]}),
            encoding="utf-8")
        (path / "data_models.json").write_text(json.dumps(
            {"data_models": [
                {"name": "Book", "fields": [{"name": "title", "type": "string"}]},
                {"name": "Author", "fields": [
                    {"name": "id", "type": "int", "primary_key": True}]}]}),
            encoding="utf-8")
        (path / "components.json").write_text(json.dumps(
            {"components": {
                "facade": {"type": "cli", "technology": "argparse",
                           "invocation": {"commands": [
                               {"name": "book", "options": [],
                                "subcommands": [
                                    {"name": "add", "options": [
                                        {"name": "--author-id", "type": "int"}]}]}]}}}}),
            encoding="utf-8")
        (path / "requirements.txt").write_text("req", encoding="utf-8")
        for name in ("errors", "pattern_matches", "intentions", "invariants"):
            (path / f"{name}.json").write_text(json.dumps({name: []}),
                                               encoding="utf-8")

    def test_create_offer_writes_the_model_and_records_the_spec(self):
        from review_aliases import run_review
        from kernel.extraction import aliases as _aliases
        with tempfile.TemporaryDirectory() as directory:
            self.setup_dir(directory)
            asked, answered = run_review(
                directory, input_fn=lambda _: "1", out_fn=lambda _: None)
            self.assertEqual((asked, answered), (1, 1))
            models = json.loads(
                (Path(directory) / "data_models.json").read_text(encoding="utf-8"))
            book = next(m for m in models["data_models"] if m["name"] == "Book")
            added = next(f for f in book["fields"] if f["name"] == "author_id")
            self.assertEqual(
                (added["type"], added["nullable"], added["status"],
                 added["foreign_key"]),
                ("int", False, "deduced",
                 {"target_entity": "Author", "target_field": "id",
                  "relationship": "many_to_one"}))
            saved = _aliases.load_aliases(directory)
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["create"]["name"], "author_id")
            self.assertIn("requirements_sha", saved[0])

    def test_second_run_applies_the_recorded_creation(self):
        from review_aliases import run_review
        from kernel.extraction import aliases as _aliases
        with tempfile.TemporaryDirectory() as directory:
            self.setup_dir(directory)
            run_review(directory, input_fn=lambda _: "1", out_fn=lambda _: None)
            fresh = [{"name": "Book", "fields": [{"name": "title"}]}]
            log = Log()
            _aliases.apply_model_fields(
                fresh, _aliases.load_aliases(directory), log,
                requirements_text="req")
            names = [f["name"] for f in fresh[0]["fields"]]
            self.assertIn("author_id", names)
            self.assertTrue(any("recorded created field" in line for line in log.lines))

    def test_rerun_without_the_create_stays_open(self):
        """Answering rename for an uncreatable pair still records the mapping."""
        from review_aliases import run_review
        with tempfile.TemporaryDirectory() as directory:
            self.setup_dir(directory)
            asked, answered = run_review(
                directory, input_fn=lambda _: "skip", out_fn=lambda _: None)
            self.assertEqual((asked, answered), (1, 0))


class ApplyModelFieldsTests(unittest.TestCase):
    def models(self):
        return [{"name": "Book", "fields": [{"name": "title"}]}]

    def record(self, **overrides):
        base = {"action": "add_book", "field": "author_id",
                "flag": "author_id",
                "create": {"entity": "Book", "name": "author_id", "type": "int",
                           "nullable": False, "unique": False,
                           "foreign_key": None, "status": "deduced"}}
        base.update(overrides)
        return base

    def test_idempotent_second_application(self):
        from kernel.extraction import aliases as _aliases
        models = self.models()
        _aliases.apply_model_fields(models, [self.record()], Log())
        before = json.dumps(models, sort_keys=True)
        _aliases.apply_model_fields(models, [self.record()], Log())
        self.assertEqual(json.dumps(models, sort_keys=True), before)
        self.assertIn("author_id", [f["name"] for f in models[0]["fields"]])

    def test_predated_prompt_drops_the_creation(self):
        from kernel.extraction import aliases as _aliases
        from kernel.extraction.decisions import requirements_sha
        models = self.models()
        record = self.record(requirements_sha=requirements_sha("old"))
        log = Log()
        _aliases.apply_model_fields(models, [record], log,
                                    requirements_text="new words")
        self.assertEqual([f["name"] for f in models[0]["fields"]], ["title"])
        self.assertTrue(any("predates a prompt change" in line for line in log.lines))

    def test_missing_entity_is_skipped(self):
        from kernel.extraction import aliases as _aliases
        models = self.models()
        record = self.record()
        record["create"] = dict(record["create"], entity="Nope")
        _aliases.apply_model_fields(models, [record], Log())
        self.assertEqual(len(models), 1)


if __name__ == "__main__":
    unittest.main()
