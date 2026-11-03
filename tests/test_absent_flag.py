"""An absent no-value flag is not passed to the method.

Click parses a missing presence flag as `False`. The dispatch passed it on,
and a body that reads `False` as "inactive only" made plain `member list`
print nothing, while `member list --active-only` worked. A presence flag that
was not given leaves the method's own default in force.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import test_generator  # noqa: E402


class AbsentFlagTests(unittest.TestCase):
    def setUp(self):
        self.helper = test_generator.CliChoiceTests(
            "test_recorded_route_wins_when_its_flag_is_passed")
        ctx = self.helper.member_ctx([])
        ctx["adapters"][0]["input_fields"] = [{
            "field_name": "active_only", "target_param": "active_only",
            "transform": "DIRECT", "required": False}]
        ctx["repositories"][0]["methods"][0]["params"] = [
            {"name": "active_only", "type": "bool"}]
        self.text, _stats = self.helper.emitted(ctx)

        class MemberRepository:
            def __init__(self, store):
                pass

            def read_all_members(self, active_only=None):
                return [f"active_only={active_only!r}"]

        self.factories = {"MemberRepository": MemberRepository}

    def run_member_list(self, *flags):
        return self.helper.run_cli(
            self.text, self.factories,
            ["--db", ":memory:", "member", "list", *flags])

    def test_without_the_flag_the_method_default_applies(self):
        code, output = self.run_member_list()
        self.assertEqual(code, 0)
        self.assertIn("active_only=None", output)

    def test_with_the_flag_the_method_receives_true(self):
        code, output = self.run_member_list("--active-only")
        self.assertEqual(code, 0)
        self.assertIn("active_only=True", output)

    def test_both_cli_backends_skip_a_false_flag(self):
        self.assertIn("given is None or given is False", self.text)


if __name__ == "__main__":
    unittest.main()
