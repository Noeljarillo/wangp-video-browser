"""P4.1 semantic search: core bridge (stdlib) and, when numpy is present, the index + 5,000-clip latency."""

import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

import semantic_host  # noqa: E402

try:
    import numpy as np
except ImportError:  # system python without the add-on
    np = None


class FakeWorker(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({"results": [{"path": "/v/b.mp4", "frame": 3, "time": 3.0, "score": 0.4},
                                       {"path": "/v/gone.mp4", "frame": 0, "time": 0, "score": 0.3}],
                           "clips": 2, "ms_total": 12.0}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class CoreBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.port_file = Path(self.tmp.name) / "port.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_absent_worker_is_calm(self):
        out = semantic_host.search("night", {}, port_file=self.port_file)
        self.assertFalse(out["available"])
        self.assertEqual(out["results"], [])

    def test_stale_port_is_unavailable(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeWorker)
        port = server.server_address[1]
        server.server_close()
        self.port_file.write_text(json.dumps({"port": port}))
        self.assertFalse(semantic_host.search("night", {}, port_file=self.port_file, timeout=1)["available"])

    def test_maps_paths_to_ids_and_drops_unknown(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeWorker)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            self.port_file.write_text(json.dumps({"port": server.server_address[1]}))
            out = semantic_host.search("night", {"/v/b.mp4": {"id": "B"}}, port_file=self.port_file)
        finally:
            server.shutdown()
        self.assertTrue(out["available"])
        self.assertEqual(out["results"], [{"id": "B", "time": 3.0, "frame": 3, "score": 0.4}])

    def test_empty_query(self):
        self.assertEqual(semantic_host.search("  ", {}, port_file=self.port_file)["results"], [])


@unittest.skipIf(np is None, "numpy not installed (analysis add-on venv only)")
class IndexTests(unittest.TestCase):
    def setUp(self):
        from analysis import semantic
        self.semantic = semantic

    def _unit(self, rows):
        m = np.random.default_rng(0).standard_normal((rows, 768)).astype(np.float32)
        return (m / np.linalg.norm(m, axis=1, keepdims=True)).astype(np.float16)

    def test_best_clip_and_frame(self):
        m = self._unit(10)
        index = self.semantic.Index(m, ["a", "b"], ["/a", "/b"], [0, 4], [[0, 1, 2, 3], [0, 2, 4, 6, 8, 10]])
        hits = index.top(m[7].astype(np.float32), k=2)
        self.assertEqual((hits[0]["path"], hits[0]["frame"], hits[0]["time"]), ("/b", 3, 6.0))
        self.assertEqual(len(hits), 2)
        self.assertEqual([h["path"] for h in index.top(m[7].astype(np.float32), allowed={"/a"})], ["/a"])

    def test_build_index_from_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "semantic"
            folder.mkdir()
            for key, n in (("k1", 3), ("k2", 2)):
                np.save(folder / f"{key}.npy", self._unit(n))
                (folder / f"{key}.json").write_text(json.dumps({"path": f"/{key}", "times": list(range(n))}))
            index = self.semantic.build_index(tmp)
            self.assertEqual(index.matrix.shape, (5, 768))
            self.assertEqual(index.matrix.dtype, np.float16)
            self.assertEqual(list(index.offsets), [0, 3])
            self.assertTrue((folder / "index.npy").is_file())

    def test_5000_clip_query_under_300ms(self):
        clips, per = 5000, 32
        m = self._unit(clips * per)
        index = self.semantic.Index(m, [str(i) for i in range(clips)], [str(i) for i in range(clips)],
                                    list(range(0, clips * per, per)), [list(range(per))] * clips)
        q = m[12345].astype(np.float32)
        index.top(q)  # builds the float32 copy once per index (done at worker start / on rebuild)
        started = time.perf_counter()
        hits = index.top(q, k=50)
        elapsed = (time.perf_counter() - started) * 1000
        print(f"\n[P4.1] 5000x32 matrix search: {elapsed:.1f} ms", file=sys.stderr)
        self.assertEqual(hits[0]["key"], str(12345 // per))
        self.assertLess(elapsed, 300)


if __name__ == "__main__":
    unittest.main()
