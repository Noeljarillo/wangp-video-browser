"""P4.3 captions: the loopback rule, the frame choice, and a real request against a stub.

The stub is a stdlib HTTP server that speaks the OpenAI chat-completions shape, so the
request the add-on builds (base64 image part, model id, max_tokens) is exercised end to
end without contacting any real model. Turning the feature on for real is the user's call.
"""

import base64
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "app"))

try:
    from analysis import captions

    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


class StubHandler(BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        StubHandler.seen.append(body)
        reply = {"choices": [{"message": {"content": "A woman in a white dress on a rooftop."}}]}
        payload = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class EndpointTest(unittest.TestCase):
    def test_only_loopback_is_allowed(self):
        self.assertEqual(captions.check_endpoint("http://127.0.0.1:1234/v1"), "http://127.0.0.1:1234/v1")
        self.assertEqual(captions.check_endpoint("http://localhost:11434/v1/"), "http://localhost:11434/v1")
        for bad in ("http://192.168.1.10:1234/v1", "https://api.openai.com/v1", "", None):
            with self.assertRaises(captions.BadEndpoint, msg=str(bad)):
                captions.check_endpoint(bad)

    def test_frames_are_spread_across_the_clip(self):
        manifest = {"paths": [f"/f/{i}.jpg" for i in range(10)], "times": list(range(10))}
        picked = captions.pick_frames(manifest, 3)
        self.assertEqual([p["frame"] for p in picked], [0, 4, 9])   # first, middle, last
        self.assertEqual(len(captions.pick_frames({"paths": ["/a.jpg"]}, 3)), 1)

    def test_no_model_configured_means_no_calls(self):
        result = captions.run_job({"path": "/x.mp4", "key": "k"}, {"cache": "/tmp", "captions": {}})
        self.assertEqual(result["skipped"], "not configured")


@unittest.skipUnless(HAVE_DEPS, "add-on deps not installed")
class RequestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), StubHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_a_caption_request_sends_the_image_and_the_model(self):
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="cap-"))
        (tmp / "frames").mkdir()
        image = tmp / "frames" / "f0.jpg"
        image.write_bytes(b"\xff\xd8\xff\xd9")          # a tiny non-image is enough here
        manifest = {"paths": [str(image)], "times": [0.0], "prompt": "a woman on a rooftop"}
        settings = {"endpoint": f"http://127.0.0.1:{self.port}/v1", "model": "stub-vlm", "frames": 1}
        StubHandler.seen.clear()
        result = captions.analyse(tmp, "k1", "/v/a.mp4", settings, text_encoder=None, manifest=manifest)

        self.assertEqual(len(StubHandler.seen), 1)
        sent = StubHandler.seen[0]
        self.assertEqual(sent["model"], "stub-vlm")
        self.assertEqual(sent["max_tokens"], 120)
        parts = sent["messages"][0]["content"]
        self.assertEqual(parts[0]["type"], "text")
        self.assertTrue(parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        decoded = base64.b64decode(parts[1]["image_url"]["url"].split(",", 1)[1])
        self.assertEqual(decoded, image.read_bytes())
        self.assertEqual(result["captions"][0]["text"], "A woman in a white dress on a rooftop.")
        self.assertIsNone(result["adherence"])           # no text encoder in this test

    def test_an_unreachable_endpoint_is_recorded_per_frame_not_raised(self):
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="cap-"))
        image = tmp / "f0.jpg"
        image.write_bytes(b"\xff\xd8\xff\xd9")
        manifest = {"paths": [str(image)], "times": [0.0]}
        settings = {"endpoint": "http://127.0.0.1:9/v1", "model": "stub-vlm", "frames": 1}
        result = captions.analyse(tmp, "k2", "/v/a.mp4", settings, manifest=manifest)
        self.assertIn("error", result["captions"][0])
        self.assertIsNone(result["adherence"])


class HostTest(unittest.TestCase):
    def test_payload_reports_settings_and_captions(self):
        import json as _json
        import tempfile

        import captions_host

        tmp = Path(tempfile.mkdtemp(prefix="caphost-"))
        results = tmp / "results"
        results.mkdir()
        (results / "a.json").write_text(_json.dumps({"path": "/v/a.mp4", "captions": [{"text": "hi"}],
                                                     "adherence": 55.0, "model": "stub"}), encoding="utf-8")
        settings = tmp / "captions.json"
        settings.write_text(_json.dumps({"endpoint": "http://127.0.0.1:1234/v1", "model": "stub"}), encoding="utf-8")
        body = captions_host.payload([{"id": "1", "path": "/v/a.mp4"}], folder=results, settings_path=settings)
        self.assertTrue(body["settings"]["enabled"])
        self.assertEqual(body["clips"]["1"]["adherence"], 55.0)
        off = captions_host.payload([{"id": "1", "path": "/v/a.mp4"}], folder=results,
                                    settings_path=tmp / "missing.json")
        self.assertFalse(off["settings"]["enabled"])


if __name__ == "__main__":
    unittest.main()
