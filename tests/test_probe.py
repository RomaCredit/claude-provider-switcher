import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from claude_provider_switcher.probe import endpoint, probe
from claude_provider_switcher.profiles import Profile
from claude_provider_switcher.storage import SwitcherError


SECRET = "test-probe-secret-not-a-real-key"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        self.server.requests.append((self.path, dict(self.headers), None))
        self.reply()

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.requests.append((self.path, dict(self.headers), json.loads(body)))
        self.reply()

    def reply(self):
        self.send_response(self.server.code)
        if self.server.code == 302:
            self.send_header("Location", self.server.redirect)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.server.body)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.requests = []
        self.server.code = 200
        self.server.body = b'{"data":[]}'
        self.server.redirect = ""
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.profile = Profile("api", f"http://127.0.0.1:{self.server.server_port}", "test-model")

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_models_api_key_header(self):
        result = probe(self.profile, SECRET)
        self.assertTrue(result["ok"])
        path, headers, body = self.server.requests[0]
        self.assertEqual(path, "/v1/models")
        self.assertEqual(headers.get("X-Api-Key"), SECRET)
        self.assertNotIn("Authorization", headers)
        self.assertIsNone(body)
        self.assertNotIn(SECRET, json.dumps(result))

    def test_bearer_and_explicit_one_token_inference(self):
        self.server.body = b'{"type":"message","content":[]}'
        profile = Profile("api", self.profile.base_url + "/v1/", "custom-model", "auth_token")
        result = probe(profile, SECRET, inference=True)
        self.assertEqual(result["test"], "inference")
        path, headers, body = self.server.requests[0]
        self.assertEqual(path, "/v1/messages")
        self.assertEqual(headers["Authorization"], "Bearer " + SECRET)
        self.assertNotIn("X-Api-Key", headers)
        self.assertEqual(body["max_tokens"], 1)
        self.assertEqual(body["model"], "custom-model")
        self.assertEqual(body["messages"], [{"role": "user", "content": "."}])

    def test_redirect_never_forwards_credentials(self):
        self.server.code = 302
        self.server.redirect = self.profile.base_url + "/stolen"
        with self.assertRaises(SwitcherError) as caught:
            probe(self.profile, SECRET)
        self.assertIn("Redirect refused", str(caught.exception))
        self.assertEqual(len(self.server.requests), 1)

    def test_error_bodies_not_exposed(self):
        for code in (401, 403, 404, 429, 500):
            self.server.code = code
            self.server.body = SECRET.encode()
            with self.subTest(code=code), self.assertRaises(SwitcherError) as caught:
                probe(self.profile, SECRET)
            self.assertIn(str(code), str(caught.exception))
            self.assertNotIn(SECRET, str(caught.exception))

    def test_invalid_or_oversized_response(self):
        for body in (b"<html>" + SECRET.encode(), b"[]", b'{"wrong":[]}', b"x" * (1024 * 1024 + 1)):
            self.server.body = body
            with self.assertRaises(SwitcherError) as caught:
                probe(self.profile, SECRET)
            self.assertNotIn(SECRET, str(caught.exception))

    def test_connection_error_redacted(self):
        class FailedOpener:
            def open(self, *_args, **_kwargs):
                raise OSError(SECRET)

        with self.assertRaises(SwitcherError) as caught:
            probe(self.profile, SECRET, opener=FailedOpener())
        self.assertNotIn(SECRET, str(caught.exception))

    def test_subscription_and_url_joining(self):
        with self.assertRaises(SwitcherError):
            probe(Profile("subscription"), SECRET)
        self.assertEqual(endpoint("https://example.com/api/v1/", "messages"), "https://example.com/api/v1/messages")
        self.assertEqual(endpoint("https://example.com", "models"), "https://example.com/v1/models")
