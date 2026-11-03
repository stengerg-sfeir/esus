"""A confirmed contract can say a read must reach a related model's field.

A search described as matching "author name" compared the query with the
`author_id` key and matched nothing a person typed. The proposal comes from
the foreign keys and the method's own words; the gate checks the body reads
the related model. Each test pins a decision, silence included.
"""

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generator  # noqa: E402
import review_contracts  # noqa: E402
from kernel.extraction import contracts  # noqa: E402


def field(name, primary_key=False, foreign_key=None):
    return {"name": name, "type": "int" if primary_key or foreign_key
            else "string", "primary_key": primary_key,
            "foreign_key": foreign_key}


CTX = {
    "entity_names": ["Book", "Author"],
    "models": [
        {"name": "Author", "fields": [field("id", True), field("name")]},
        {"name": "Book", "fields": [
            field("id", True), field("title"), field("isbn"),
            field("author_id", foreign_key={"target_entity": "Author",
                                            "target_field": "id"})]},
    ],
    "repositories": [
        {"entity": "Book", "interface_name": "BookRepository", "methods": []},
        {"entity": "Author", "interface_name": "AuthorRepository",
         "methods": []},
    ],
}

SEARCH = {"name": "search", "description": "Case-insensitive substring "
          "search across title, author name, and ISBN.",
          "params": [{"name": "query", "type": "str"}], "raises": []}


def propose(method=SEARCH, holder="BookRepository", role="repository"):
    return review_contracts._propose(CTX, holder, method, role, "")


class SchemaTests(unittest.TestCase):
    def test_a_read_is_kept_and_a_malformed_one_dropped(self):
        record = contracts.normalize_contract({
            "holder": "H", "method": "m",
            "reads": [{"entity": "Author", "field": "name",
                       "repository": "AuthorRepository",
                       "via": "Book.author_id"},
                      {"entity": "Author"}, "junk"]})
        self.assertEqual(record["reads"], [{
            "entity": "Author", "field": "name",
            "repository": "AuthorRepository", "via": "Book.author_id"}])


class ProposalTests(unittest.TestCase):
    def test_a_related_field_the_text_names_is_proposed(self):
        proposal = propose()
        self.assertEqual(proposal["reads"], [{
            "entity": "Author", "field": "name", "via": "Book.author_id",
            "repository": "AuthorRepository"}])
        ids = [question["id"] for question in proposal["questions"]]
        self.assertIn("keep_reads", ids)

    def test_an_entity_without_a_field_proposes_nothing(self):
        method = dict(SEARCH, description="Searches across title/author/isbn.")
        self.assertIsNone(propose(method))

    def test_a_key_field_is_never_proposed(self):
        method = dict(SEARCH, description="Filters by author id.")
        self.assertIsNone(propose(method))

    def test_a_model_without_the_relation_proposes_nothing(self):
        self.assertIsNone(propose(holder="AuthorRepository"))

    def test_a_service_method_is_not_proposed_a_read(self):
        self.assertIsNone(propose(role="service", holder="BookService"))


class FinalizeTests(unittest.TestCase):
    def finalize(self, answers):
        return review_contracts._finalize(propose(), answers, "sha", CTX)

    def test_a_kept_read_reaches_the_record(self):
        self.assertEqual(self.finalize({"keep_reads": "keep"})["reads"][0]
                         ["entity"], "Author")

    def test_a_dropped_read_does_not(self):
        self.assertEqual(self.finalize({"keep_reads": "drop"})["reads"], [])


READ = {"entity": "Author", "field": "name", "via": "Book.author_id",
        "repository": "AuthorRepository"}


def complaints(body):
    return generator._contract_complaints(ast.parse(body), {"reads": [READ]})


class GateTests(unittest.TestCase):
    def test_matching_the_key_is_refused(self):
        found = complaints(
            "for record in self._store.all(self.ENTITY):\n"
            "    if query in str(record['author_id']):\n        pass\n")
        self.assertEqual(found, [
            "the confirmed contract reads `Author.name`, but the body never "
            "reads `Author`"])

    def test_reading_the_entity_through_the_store_is_accepted(self):
        self.assertEqual(complaints(
            "authors = self._store.select('Author', [])\n"
            "names = [row['name'] for row in authors]\n"), [])

    def test_reading_it_through_the_repository_is_accepted(self):
        self.assertEqual(complaints(
            "authors = self._repos['AuthorRepository'].read_all()\n"
            "names = [author.name for author in authors]\n"), [])

    def test_reading_the_entity_but_not_the_field_is_refused(self):
        found = complaints(
            "authors = self._store.select('Author', [])\n"
            "ids = [row['id'] for row in authors]\n")
        self.assertEqual(found, [
            "the confirmed contract reads `Author.name`, but the body never "
            "uses its `name`"])

    def test_a_contract_without_reads_adds_no_complaint(self):
        self.assertEqual(generator._contract_complaints(
            ast.parse("pass"), {"effects": []}), [])


class PromptTests(unittest.TestCase):
    def test_the_prompt_names_the_related_field(self):
        text = "\n".join(generator._contract_lines({"reads": [READ]}))
        self.assertIn("read `Author.name`", text)
        self.assertIn("Book.author_id", text)


if __name__ == "__main__":
    unittest.main()
