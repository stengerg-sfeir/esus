"""The model runtime owns one llama-server at a time and cleans it up."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import model_runtime  # noqa: E402


class FakeProcess:
    def __init__(self, *args, **kwargs):
        self.args = args[0] if args else []
        self.pid = 424242
        self.returncode = None
        self.waited = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.waited = True
        self.returncode = 0
        return 0


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class RuntimeTests(unittest.TestCase):
    def profile(self, directory, environment="mac"):
        model = Path(directory) / "model.gguf"
        model.write_bytes(b"fake")
        return model_runtime.profile_for(
            "writer", model_path=str(model), state_dir=Path(directory),
            environment=environment)

    def test_mac_is_one_slot_and_16k(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = self.profile(directory)
        self.assertEqual((profile.slots, profile.context), (1, 16384))

    def test_kaggle_is_two_slots_and_32k_total(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = self.profile(directory, "kaggle")
        self.assertEqual((profile.slots, profile.context), (2, 32768))

    def test_command_contains_the_profile_values(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = self.profile(directory, "kaggle")
            profile.binary = "/bin/echo"
            command = profile.command()
        self.assertIn("-np", command)
        self.assertEqual(command[command.index("-np") + 1], "2")
        self.assertEqual(command[command.index("-c") + 1], "32768")

    def test_start_waits_for_health_and_stop_terminates_owned_process(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = self.profile(directory)
            profile.binary = "/bin/echo"
            process = FakeProcess()
            with mock.patch.object(model_runtime, "_port_open", return_value=False), \
                    mock.patch.object(model_runtime.subprocess, "Popen",
                                      return_value=process) as popen, \
                    mock.patch.object(model_runtime.urllib.request, "urlopen",
                                      return_value=FakeResponse()), \
                    mock.patch.object(model_runtime.os, "killpg") as killpg:
                server = model_runtime.LlamaServer(profile)
                server.start()
                self.assertTrue(profile.state_path.is_file())
                self.assertEqual(popen.call_args.args[0], profile.command())
                server.stop()
                killpg.assert_called()
            self.assertFalse(profile.state_path.exists())

    def test_a_busy_port_is_refused_without_killing_anything(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = self.profile(directory)
            with mock.patch.object(model_runtime, "_port_open", return_value=True), \
                    mock.patch.object(model_runtime.subprocess, "Popen") as popen:
                with self.assertRaises(RuntimeError):
                    model_runtime.LlamaServer(profile).start()
            popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
