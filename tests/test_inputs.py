import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import inputs  # noqa: E402
import server  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png-body"
JPG = b"\xff\xd8\xff\xe0" + b"fake-jpg-body"


def box(kind, payload=b""):
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


def freeform(name, datas):
    body = box(b"mean", b"\0\0\0\0com.apple.iTunes") + box(b"name", b"\0\0\0\0" + name.encode())
    for type_code, data in datas:
        body += box(b"data", type_code.to_bytes(4, "big") + b"\0\0\0\0" + data)
    return box(b"----", body)


def mp4_with_embedded(images, layout):
    ilst = box(b"ilst", freeform("EMBEDDED_IMAGES", images)
               + freeform("IMAGE_METADATA", [(1, json.dumps(layout).encode())]))
    meta = box(b"meta", b"\0\0\0\0" + box(b"hdlr", b"\0" * 25) + ilst)
    return box(b"ftyp", b"isom\0\0\0\0") + box(b"moov", box(b"udta", meta))


class InputsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.root = self.dir / "app" / "outputs"
        self.root.mkdir(parents=True)
        (self.dir / "app" / "refs").mkdir()
        (self.dir / "app" / "refs" / "face.png").write_bytes(PNG)
        (self.dir / "abs.jpg").write_bytes(JPG)
        self.clip = self.root / "clip.mp4"
        self.clip.write_bytes(box(b"ftyp", b"isom"))

    def tearDown(self):
        self.tmp.cleanup()

    def entry(self, meta, path=None):
        path = path or self.clip
        return {"id": "abc", "path": str(path), "root": str(self.root), "meta": meta,
                "size": path.stat().st_size, "mtime": path.stat().st_mtime}

    def test_wangp_paths_resolve_and_missing_reported(self):
        meta = {"image_start": str(self.dir / "abs.jpg"),
                "image_refs": ["refs/face.png", "/nope/missing.png"], "video_guide": None}
        refs = inputs.collect(self.entry(meta))
        self.assertEqual([r["key"] for r in refs], ["image_start", "image_refs", "image_refs"])
        self.assertEqual([r["exists"] for r in refs], [True, True, False])
        self.assertEqual(refs[2]["recorded"], "/nope/missing.png")
        self.assertNotIn("_path", inputs.public(refs)[0])

    def test_comfy_loadimage(self):
        (self.dir / "app" / "input").mkdir()
        (self.dir / "app" / "input" / "girl.png").write_bytes(PNG)
        meta = {"_comfy": {"prompt": {"3": {"class_type": "LoadImage", "inputs": {"image": "girl.png [input]"}},
                                      "4": {"class_type": "KSampler", "inputs": {"seed": 1}}}}}
        refs = inputs.collect(self.entry(meta))
        self.assertEqual(len(refs), 1)
        self.assertTrue(refs[0]["exists"])
        self.assertEqual(refs[0]["name"], "girl.png")

    def test_embedded_mp4_images(self):
        clip = self.root / "emb.mp4"
        clip.write_bytes(mp4_with_embedded([(14, PNG), (13, JPG)],
                                           {"image_refs": [{"index": 0, "filename": "a.png"}, {"index": 1, "filename": "b.jpg"}]}))
        refs = inputs.collect(self.entry({}, clip))
        self.assertEqual([(r["name"], r["source"]) for r in refs], [("a.png", "embedded"), ("b.jpg", "embedded")])
        self.assertEqual(inputs.read_embedded(inputs.lookup(self.entry({}, clip), "1")), JPG)
        self.assertEqual(refs[0]["_mime"], "image/png")

    def test_lookup_rejects_bad_n(self):
        entry = self.entry({"image_start": "/nope/missing.png"})
        for bad in ("0", "1", "-1", "../../etc/passwd", "0/../../x", ""):
            self.assertIsNone(inputs.lookup(entry, bad), bad)


class InputsHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        (base / "ref.png").write_bytes(PNG)
        clip = base / "c.mp4"
        clip.write_bytes(box(b"ftyp", b"isom"))
        entry = {"id": "vid1", "path": str(clip), "root": str(base), "size": 1, "mtime": 1,
                 "meta": {"image_refs": [str(base / "ref.png"), str(base / "gone.png")]}}
        server._index["videos"] = [entry]
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        server._index["videos"] = []
        cls.tmp.cleanup()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_listing_and_serving(self):
        status, body = self.get("/api/inputs/vid1")
        refs = json.loads(body)["inputs"]
        self.assertEqual(status, 200)
        self.assertEqual([r["exists"] for r in refs], [True, False])
        self.assertEqual(self.get("/input/vid1/0"), (200, PNG))
        self.assertEqual(self.get("/input/vid1/1")[0], 404)  # recorded but missing

    def test_path_traversal_is_404(self):
        for path in ("/input/vid1/../../etc/passwd", "/input/vid1/..%2F..%2Fetc%2Fpasswd",
                     "/input/../../etc/passwd", "/input/vid1/0/../../../etc/passwd",
                     "/input/vid1/%2Fetc%2Fpasswd", "/input/nope/0"):
            self.assertEqual(self.get(path)[0], 404, path)


if __name__ == "__main__":
    unittest.main()
