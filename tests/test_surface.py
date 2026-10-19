"""Surface duplicates: shown to a human, removed on decision, never auto-removed.

A subcommand duplicating a top-level command (`expense → category` beside
`category`) is ambiguous requirements read twice — deleting either is a
judgment, so the review asks, records `{command, subcommand, keep}` with a
prompt-sha stamp, and applies the drop to the on-disk components plus every
future run while the prompt stands. The probe keeps reporting whatever
remains: this removes a node, never a finding.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import review_surface  # noqa: E402
from review_surface import (  # noqa: E402
    apply_surface_decisions,
    collect_duplicates,
    run_review,
)


def components(commands):
    return {"facade": {"type": "cli", "technology": "argparse",
                       "invocation": {"commands": commands}}}


def command(name, subs=()):
    return {"name": name, "options": [],
            "subcommands": [{"name": sub, "options": list(options)}
                            for sub, options in subs]}


def writes(directory, cmds, requirements="req"):
    path = Path(directory)
    (path / "components.json").write_text(
        json.dumps({"components": components(cmds)}), encoding="utf-8")
    (path / "requirements.txt").write_text(requirements, encoding="utf-8")
    for name in ("service_contracts", "data_models", "pattern_matches",
                 "interaction_adapters", "errors", "intentions", "invariants"):
        (path / f"{name}.json").write_text(json.dumps({name: []}),
                                           encoding="utf-8")
    return str(path)


def expenses_like():
    return [command("expense", [("category", [{"name": "--help"}]),
                                ("list", [{"name": "--category"}])]),
            command("category", [("list", [])])]


EXPENSES_REQUIREMENTS = ("Run `expense category list` and `expense list [--category]`?")


class Log:
    def __init__(self):
        self.lines = []

    def write(self, text):
        self.lines.append(text)


class CollectTests(unittest.TestCase):
    def test_duplicate_pair_is_collected_with_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            out = writes(directory, expenses_like(), EXPENSES_REQUIREMENTS)
            questions, _ = collect_duplicates(out)
            self.assertEqual(len(questions), 1)
            question = questions[0]
            self.assertEqual((question["command"], question["subcommand"]),
                             ("expense", "category"))
            self.assertIn("--help", question["leaf_flags"])
            self.assertTrue(any("expense category list" in span
                                for span in question["evidence"]))

    def test_clean_surface_asks_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            out = writes(directory, [command("book", [("add", [])])])
            self.assertEqual(collect_duplicates(out)[0], [])

    def test_decided_pairs_do_not_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            out = writes(directory, expenses_like(), EXPENSES_REQUIREMENTS)
            run_review(out, input_fn=lambda _: "1", out_fn=lambda _: None)
            self.assertEqual(collect_duplicates(out)[0], [])


class ReviewFlowTests(unittest.TestCase):
    def test_keep_parent_drops_the_subcommand(self):
        with tempfile.TemporaryDirectory() as directory:
            out = writes(directory, expenses_like(), EXPENSES_REQUIREMENTS)
            asked, answered = run_review(
                out, input_fn=lambda _: "2", out_fn=lambda _: None)
            self.assertEqual((asked, answered), (1, 1))
            cmds = json.loads(
                (Path(out) / "components.json").read_text(
                    encoding="utf-8"))["components"]["facade"]["invocation"]["commands"]
            expense = next(c for c in cmds if c["name"] == "expense")
            self.assertNotIn("category", [s["name"] for s in expense["subcommands"]])
            self.assertIn("category", [c["name"] for c in cmds])
            saved = review_surface.load_surface_decisions(out)
            self.assertEqual(saved[0]["keep"], "parent")

    def test_keep_both_records_without_touching(self):
        with tempfile.TemporaryDirectory() as directory:
            before = expenses_like()
            out = writes(directory, [dict(c) for c in before], EXPENSES_REQUIREMENTS)
            asked, answered = run_review(
                out, input_fn=lambda _: "1", out_fn=lambda _: None)
            self.assertEqual((asked, answered), (1, 1))
            cmds = json.loads(
                (Path(out) / "components.json").read_text(
                    encoding="utf-8"))["components"]["facade"]["invocation"]["commands"]
            self.assertEqual(
                [(c["name"], [s["name"] for s in c["subcommands"]]) for c in cmds],
                [(c["name"], [s["name"] for s in c["subcommands"]]) for c in before])

    def test_skip_records_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            out = writes(directory, expenses_like(), EXPENSES_REQUIREMENTS)
            asked, answered = run_review(
                out, input_fn=lambda _: "skip", out_fn=lambda _: None)
            self.assertEqual((asked, answered), (1, 0))
            self.assertEqual(review_surface.load_surface_decisions(out), [])


class ApplyTests(unittest.TestCase):
    def test_predated_prompt_drops_the_record_with_a_log_line(self):
        body = components(expenses_like())
        log = Log()
        record = {"command": "expense", "subcommand": "category",
                  "keep": "parent",
                  "requirements_sha": "0" * 64}
        out = apply_surface_decisions(body, [record], log,
                                      requirements_text="changed prompt")
        self.assertEqual(out, body)
        self.assertTrue(any("predates a prompt change" in line for line in log.lines))

    def test_stale_nodes_apply_to_nothing(self):
        body = components([command("book", [("add", [])])])
        record = {"command": "expense", "subcommand": "category",
                  "keep": "parent"}
        self.assertEqual(apply_surface_decisions(body, [record], Log()), body)

    def test_keep_sub_drops_the_top_level_command(self):
        body = components(expenses_like())
        record = {"command": "expense", "subcommand": "category",
                  "keep": "sub"}
        out = apply_surface_decisions(body, [record], Log())
        names = [c["name"] for c in out["facade"]["invocation"]["commands"]]
        self.assertNotIn("category", names)
        expense = next(c for c in out["facade"]["invocation"]["commands"]
                       if c["name"] == "expense")
        self.assertIn("category", [s["name"] for s in expense["subcommands"]])


def stranded():
    """A library-like output: `member list -active-only` has no adapter field.

    The documents link the flag to nothing; the leaf reads the parameterless
    `read_all_members`, and its sibling parameterless reads are the finite
    candidates a human may pick from.
    """
    return {
        "components": components([
            {"name": "member", "options": [], "subcommands": [
                {"name": "list", "options": [
                    {"name": "-active-only", "short": "-a", "type": "bool",
                     "required": False, "default": None}]}]}]),
        "data_models": [{"name": "Member", "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "name", "type": "string"},
            {"name": "is_active", "type": "boolean"}]}],
        "interaction_adapters": [
            {"action_name": "list_members",
             "target_service": "MemberRepository",
             "target_method": "read_all_members", "input_fields": []}],
        "persistence_ports": {
            "repositories": [
                {"entity": "Member", "interface_name": "MemberRepository",
                 "methods": [
                     {"name": "read_all_members", "params": [],
                      "return_type": "List[Member]"},
                     {"name": "find_active_members", "params": [],
                      "return_type": "List[Member]"},
                     {"name": "find_members_by_name",
                      "params": [{"name": "name", "type": "str"}],
                      "return_type": "List[Member]"}]}],
            "entity_mappings": [
                {"entity": "Member", "table": "members",
                 "primary_key": "id", "indexes": []}]},
        "pattern_matches": [
            {"source": "contract:MemberRepository.read_all_members",
             "pattern_id": "READ_ALL", "decision": "decided"},
            {"source": "contract:MemberRepository.find_active_members",
             "pattern_id": "READ_ALL", "decision": "decided"},
            {"source": "contract:MemberRepository.find_members_by_name",
             "pattern_id": "READ_ALL", "decision": "decided"}],
        "service_contracts": [], "errors": [], "intentions": [],
        "invariants": [],
    }


def writes_stranded(directory, records=None):
    path = Path(directory)
    for name, body in stranded().items():
        (path / f"{name}.json").write_text(json.dumps({name: body}),
                                           encoding="utf-8")
    # `find_active_members` reads as any parameterless filter — nothing but a
    # human answer says `is_active == True`; that answer is what makes the
    # method a candidate (a stub can be routed into, never fixed by routing).
    (path / "method_slots.json").write_text(json.dumps({"slots": [
        {"holder": "MemberRepository", "method": "find_active_members",
         "pattern": "FILTER_CRITERION",
         "slots": {"criterion_field": "is_active", "criterion_value": "True"},
         "decided_by": "user"}]}), encoding="utf-8")
    (path / "requirements.txt").write_text(
        "Run `member list [--active-only]`.", encoding="utf-8")
    if records is not None:
        (path / "surface_decisions.json").write_text(
            json.dumps({"decisions": records}), encoding="utf-8")
    return str(path)


class RouteCollectTests(unittest.TestCase):
    """A stranded flag offers parameterless reads, and only those; the
    recorded pick dispatches and never reopens while the prompt stands."""

    def test_stranded_flag_offers_parameterless_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            out = writes_stranded(directory)
            questions, _context = review_surface.collect_routes(out)
            self.assertEqual(len(questions), 1)
            question = questions[0]
            self.assertEqual(
                (question["command"], question["subcommand"],
                 question["flag"]), ("member", "list", "active_only"))
            self.assertEqual(question["candidates"],
                             [("MemberRepository", "find_active_members")])

    def test_a_recorded_route_closes_the_question(self):
        with tempfile.TemporaryDirectory() as directory:
            out = writes_stranded(directory)
            review_surface.run_review(out, input_fn=lambda _: "1",
                                      out_fn=lambda _: None)
            self.assertEqual(review_surface.collect_routes(out)[0], [])
            records = json.loads(
                (Path(out) / "surface_decisions.json").read_text())["decisions"]
            self.assertEqual(records[0]["kind"], "route")
            self.assertEqual(records[0]["service"], "MemberRepository")
            self.assertEqual(records[0]["method"], "find_active_members")
            self.assertEqual(records[0]["decided_by"], "user")

    def test_a_route_pointing_at_a_vanished_method_reopens(self):
        record = {"kind": "route", "command": "member", "subcommand": "list",
                  "flag": "active_only", "service": "MemberRepository",
                  "method": "find_gone_members", "decided_by": "user"}
        with tempfile.TemporaryDirectory() as directory:
            out = writes_stranded(directory, [record])
            questions, _context = review_surface.collect_routes(out)
            self.assertEqual(len(questions), 1)


if __name__ == "__main__":
    unittest.main()

