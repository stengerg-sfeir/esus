"""The `--model server` backend speaks llama-server's native HTTP API.

These tests use a tiny in-process HTTP server, so they pin the request shape
(especially the GBNF string and `n_probs`) and the response translation without
loading a GGUF or requiring a real llama-server.
"""

import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.classifier.hierarchical_classifier import softmax_classify  # noqa: E402
from kernel.extraction import runner  # noqa: E402
from kernel.extraction.server_backend import ServerModel  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    requests = []

    def log_message(self, *args):
        pass

    def _send(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/props":
            self._send({
                "default_generation_settings": {"n_ctx": 4096},
                "model_alias": "test-model.gguf",
                "model_path": "/models/test-model.gguf",
                "total_slots": 2,
            })
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        self.__class__.requests.append((self.path, payload))
        if self.path == "/tokenize":
            self._send({"tokens": [1, 2, 3]})
        elif self.path == "/completion":
            if payload.get("n_probs"):
                self._send({
                    "content": " A",
                    "tokens_predicted": 1,
                    "tokens_evaluated": 7,
                    "tokens_cached": 0,
                    "stop_type": "limit",
                    "completion_probabilities": [{
                        "top_logprobs": [
                            {"token": " A", "logprob": -0.10},
                            {"token": " B", "logprob": -2.30},
                            {"token": " C", "logprob": -3.10},
                        ],
                    }],
                })
            else:
                self._send({
                    "content": "{\"ok\": true}",
                    "tokens_predicted": 3,
                    "tokens_evaluated": 5,
                    "tokens_cached": 2,
                    "stop_type": "limit",
                    "timings": {
                        "prompt_n": 5, "cache_n": 2,
                        "predicted_n": 3, "predicted_ms": 100.0,
                    },
                })
        elif self.path == "/v1/chat/completions":
            self._send({
                "choices": [{
                    "message": {"content": "return 0"},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 9, "completion_tokens": 2,
                          "total_tokens": 11},
                "timings": {"predicted_ms": 50.0, "cache_n": 7},
            })
        else:
            self._send({"error": "not found"}, 404)


class ServerBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()

    def setUp(self):
        _Handler.requests.clear()

    def test_props_and_tokenization(self):
        model = ServerModel(url=self.url)
        self.assertEqual(model.n_ctx(), 4096)
        self.assertEqual(model.model_name, "test-model.gguf")
        self.assertEqual(model.tokenize(b"hello"), [1, 2, 3])
        self.assertTrue(model.metadata["tokenizer.chat_template"])

    def test_generation_sends_the_gbnf_and_reports_decode_time(self):
        model = ServerModel(url=self.url)
        result = runner.generate(
            model, "prompt", 'root ::= "Z"', "doc",
            temperature=0.0, max_new_tokens=12, seed=7,
        )
        self.assertEqual(result.text, '{"ok": true}')
        self.assertEqual(result.tokens, 3)
        self.assertEqual(result.finish_reason, "length")
        self.assertAlmostEqual(result.decode_seconds, 0.1)
        self.assertEqual(result.prompt_tokens, 7)
        self.assertIn("decode", result.describe())

        path, payload = _Handler.requests[-1]
        self.assertEqual(path, "/completion")
        self.assertEqual(payload["grammar"], 'root ::= "Z"')
        self.assertEqual(payload["n_predict"], 16)
        self.assertEqual(payload["seed"], 7)
        self.assertEqual(payload["id_slot"], 0)

    def test_chat_completion_uses_the_openai_endpoint(self):
        model = ServerModel(url=self.url)
        result = runner.generate_chat(
            model, "write a body", "body", temperature=0.0,
            max_new_tokens=20, seed=3,
        )
        self.assertEqual(result.text, "return 0")
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.tokens, 2)
        self.assertEqual(result.prompt_tokens, 9)
        self.assertEqual(result.cached_tokens, 7)
        path, payload = _Handler.requests[-1]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(payload["seed"], 3)
        self.assertTrue(payload["cache_prompt"])
        self.assertEqual(payload["id_slot"], 0)

    def test_classifier_uses_server_top_logprobs(self):
        model = ServerModel(url=self.url)
        best, confidence, probabilities = softmax_classify(
            model, "a requirement",
            [{"id": "X", "name": "X", "description": "first"},
             {"id": "Y", "name": "Y", "description": "second"}],
        )
        self.assertEqual(best, "X")
        self.assertGreater(confidence, 0.8)
        self.assertIn("Y", probabilities)
        path, payload = _Handler.requests[-1]
        self.assertEqual(path, "/completion")
        self.assertEqual(payload["n_probs"], 15)
        self.assertEqual(payload["id_slot"], 0)

    def test_parallel_backend_omits_the_slot_and_reports_its_slot_count(self):
        model = ServerModel(url=self.url, parallel=True)
        self.assertEqual(model.total_slots, 2)
        runner.generate(model, "prompt", 'root ::= "Z"', "doc",
                        temperature=0.0, max_new_tokens=12, seed=7)
        path, payload = _Handler.requests[-1]
        self.assertEqual(path, "/completion")
        self.assertNotIn("id_slot", payload)

    def test_load_model_server_uses_the_environment_url(self):
        with mock.patch.dict(os.environ, {"LLAMA_SERVER_URL": self.url}):
            model = runner.load_model("server", quiet=True)
        self.assertIsInstance(model, ServerModel)


if __name__ == "__main__":
    unittest.main()
