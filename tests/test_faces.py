"""P3.2: detection storage, core read API and the faces handler's guards (stdlib only)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import analysis_host  # noqa: E402
import detections_api  # noqa: E402
from analysis import detstore, faces, jobqueue, worker  # noqa: E402


def row(n, frame, kind="face", emb=None):
    return {"n": n, "frame": frame, "t": float(frame), "kind": kind, "x": .1, "y": .2, "w": .3, "h": .4,
            "score": .9, "model": "sface-2021dec", "emb": emb if emb is not None else [0.5, -0.25, 1.0]}


class DetstoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "analysis.db"
        self.conn = detstore.connect(self.db)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_pack_roundtrip_float16(self):
        self.assertEqual(detstore.unpack(detstore.pack([0.5, -0.25, 1.0])), [0.5, -0.25, 1.0])
        self.assertEqual(detstore.unpack(None), [])

    def test_save_replaces_and_loads(self):
        detstore.save(self.conn, "k1", [row(0, 0), row(1, 2, "person")], {"frames": 3, "faces": 1, "persons": 1})
        detstore.save(self.conn, "k1", [row(0, 1)], {"frames": 3, "faces": 1, "persons": 0, "ms": 5})
        rows = detstore.load(self.conn, "k1", embeddings=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["frame"], 1)
        self.assertEqual(rows[0]["emb"], [0.5, -0.25, 1.0])
        self.assertEqual(detstore.run_info(self.conn, "k1")["ms"], 5)
        self.assertIsNone(detstore.run_info(self.conn, "other"))
        self.assertEqual(len(list(detstore.all_embeddings(self.conn, kind="face"))), 1)


class CoreApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.clip = root / "clip.mp4"
        self.clip.write_bytes(b"x" * 10)
        self.entry = {"id": "abc", "path": str(self.clip), "size": 10}
        self.db = root / "analysis.db"
        self.patches = [mock.patch.object(detections_api, "FACES_DIR", root / "faces"),
                        mock.patch.object(detections_api, "FRAMES_DIR", root / "frames"),
                        mock.patch.object(analysis_host, "installed", lambda: True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_absent_addon(self):
        with mock.patch.object(analysis_host, "installed", lambda: False):
            out = detections_api.detections(self.entry, db_path=self.db)
        self.assertEqual(out["state"], "absent")

    def test_pending_then_done(self):
        self.assertEqual(detections_api.detections(self.entry, db_path=self.db)["state"], "pending")
        key = detections_api.clip_key(self.entry)
        self.assertEqual(key, jobqueue.cache_key(str(self.clip), 10, os.stat(self.clip).st_mtime_ns))
        conn = detstore.connect(self.db)
        detstore.save(conn, key, [row(0, 0)], {"frames": 1, "faces": 1, "persons": 0})
        conn.close()
        out = detections_api.detections(self.entry, db_path=self.db)
        self.assertEqual(out["state"], "done")
        self.assertEqual(out["detections"][0]["crop"], "/api/analysis/crop/abc/0")
        self.assertNotIn("emb", out["detections"][0])

    def test_crop_allow_list(self):
        key = detections_api.clip_key(self.entry)
        folder = Path(self.tmp.name) / "faces" / key
        folder.mkdir(parents=True)
        (folder / "3.jpg").write_bytes(b"jpg")
        self.assertEqual(detections_api.crop_path(self.entry, "3"), folder / "3.jpg")
        self.assertIsNone(detections_api.crop_path(self.entry, "4"))
        self.assertIsNone(detections_api.crop_path(self.entry, "../x"))
        self.assertIsNone(detections_api.crop_path(None, "3"))


class HandlerTest(unittest.TestCase):
    def test_registered_and_gpu_gated(self):
        self.assertIs(worker.HANDLERS["faces"], faces.run_job)
        self.assertIn("faces", worker.NEEDS_GPU)
        self.assertIn("faces", analysis_host.KINDS)

    def test_cached_key_is_not_redone(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = detstore.connect(Path(tmp) / "analysis.db")
            detstore.save(conn, "k", [], {"frames": 2, "faces": 0, "persons": 0, "ms": 1, "device": "cpu"})
            conn.close()
            out = faces.run_job({"key": "k", "path": "x"}, {"cache": Path(tmp)})
            self.assertTrue(out["cached"])

    def test_no_frames_is_an_error_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                faces.run_job({"key": "k", "path": "x"}, {"cache": Path(tmp)})

    def test_models_never_downloaded_at_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(len(faces.missing_models(tmp)), len(faces.MODELS))


if __name__ == "__main__":
    unittest.main()
