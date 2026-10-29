"""P3.3: character clustering (add-on venv) and the core's character actions (stdlib)."""

import json
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import analysis_host  # noqa: E402
import characters_api  # noqa: E402
from analysis import detstore, jobqueue  # noqa: E402

try:
    import numpy  # noqa: F401
    import sklearn  # noqa: F401
    from analysis import characters
except ImportError:  # core interpreter without the add-on deps
    characters = None


def vec(seed, noise=0.0, dim=128):
    rnd = random.Random(seed)
    base = [rnd.gauss(0, 1) for _ in range(dim)]
    jitter = random.Random(seed * 7919 + int(noise * 1000))
    return [b + jitter.gauss(0, noise) for b in base]


class Lib:
    """Temp app dir with an analysis DB and real (empty) clip files."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Path(self.tmp.name)
        self.cache = self.app / ".cache"
        self.cache.mkdir()
        self.db = self.cache / "analysis.db"
        self.entries = []

    def clip(self, name, identity_seed, noise=0.1, frames=3):
        path = self.app / f"{name}.mp4"
        path.write_bytes(b"x")
        entry = {"id": name, "path": str(path), "size": 1}
        key = jobqueue.cache_key(str(path), 1, os.stat(path).st_mtime_ns)
        rows = [{"n": i, "frame": i, "t": float(i), "kind": "face", "x": .1, "y": .1, "w": .2, "h": .2,
                 "score": .9, "model": "sface-2021dec", "emb": vec(identity_seed, noise + i * 0.01)}
                for i in range(frames)]
        conn = detstore.connect(self.db)
        detstore.save(conn, key, rows, {"frames": frames, "faces": frames, "persons": 0})
        conn.close()
        (self.cache / "faces" / key).mkdir(parents=True, exist_ok=True)
        (self.cache / "faces" / key / "0.jpg").write_bytes(b"jpg")
        self.entries.append(entry)
        return entry

    def patches(self):
        return [mock.patch.object(characters_api, "DATA_PATH", self.app / ".data" / "characters.json"),
                mock.patch.object(characters_api, "INDEX_PATH", self.cache / "characters_index.json"),
                mock.patch.object(characters_api, "FACES_DIR", self.cache / "faces"),
                mock.patch.object(analysis_host, "installed", lambda: True)]


@unittest.skipIf(characters is None, "needs the analysis add-on venv (numpy, scikit-learn)")
class ClusterTest(unittest.TestCase):
    def setUp(self):
        self.lib = Lib()
        self.ps = self.lib.patches()
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in self.ps:
            p.stop()
        self.lib.tmp.cleanup()

    def recluster(self):
        return characters.recluster(self.lib.cache, self.lib.db, self.lib.app)

    def by_clip(self):
        out = {}
        for c in characters_api.listing(self.lib.entries)["characters"]:
            for clip in c["clips"]:
                out[clip] = c
        return out

    def test_cluster_name_merge_split_survive_reanalysis(self):
        for name, seed in (("a1", 1), ("a2", 1), ("a3", 1), ("b1", 2), ("b2", 2)):
            self.lib.clip(name, seed)
        self.assertEqual(self.recluster()["characters"], 2)
        clips = self.by_clip()
        self.assertEqual(clips["a1"]["id"], clips["a3"]["id"])
        self.assertNotEqual(clips["a1"]["id"], clips["b1"]["id"])
        a, b = clips["a1"]["id"], clips["b1"]["id"]
        self.assertEqual(characters_api.avatar_path(a).name, "0.jpg")

        characters_api.action({"op": "rename", "id": a, "name": "Mara"}, self.lib.entries)
        characters_api.action({"op": "merge", "id": a, "others": [b]}, self.lib.entries)
        self.assertEqual(self.by_clip()["b2"]["name"], "Mara")
        self.recluster()  # re-analysis keeps the name and the merge
        clips = self.by_clip()
        self.assertEqual({c["name"] for c in clips.values()}, {"Mara"})

        # a new clip of a merged identity is auto-assigned to the named character
        self.lib.clip("b3", 2, noise=0.15)
        self.recluster()
        self.assertEqual(self.by_clip()["b3"]["name"], "Mara")

        # split b* off again; it survives a re-cluster
        out = characters_api.action({"op": "split", "id": a, "clips": ["b1", "b2", "b3"], "name": "Ilo"},
                                    self.lib.entries)
        self.recluster()
        clips = self.by_clip()
        self.assertEqual(clips["b1"]["id"], out["id"])
        self.assertEqual(clips["b3"]["name"], "Ilo")
        self.assertEqual(clips["a2"]["name"], "Mara")

    def test_ignore_and_threshold(self):
        self.lib.clip("a1", 1)
        self.recluster()
        cid = self.by_clip()["a1"]["id"]
        characters_api.action({"op": "ignore", "id": cid}, self.lib.entries)
        self.recluster()
        self.assertTrue(self.by_clip()["a1"]["ignored"])
        characters_api.action({"op": "settings", "assign_face": 0.6}, self.lib.entries)
        data = json.loads((self.lib.app / ".data" / "characters.json").read_text())
        self.assertEqual(data["settings"]["assign_face"], 0.6)
        with self.assertRaises(ValueError):
            characters_api.action({"op": "settings", "assign_face": 2}, self.lib.entries)


class CoreOnlyTest(unittest.TestCase):
    def test_listing_without_any_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(characters_api, "INDEX_PATH", Path(tmp) / "none.json"), \
                    mock.patch.object(characters_api, "DATA_PATH", Path(tmp) / "none2.json"):
                out = characters_api.listing([])
                self.assertEqual(out["characters"], [])
                with self.assertRaises(ValueError):
                    characters_api.action({"op": "rename", "id": "nope"}, [])
                self.assertIsNone(characters_api.avatar_path("../../etc"))

    def test_worker_registers_characters(self):
        from analysis import worker
        self.assertIn("characters", worker.HANDLERS)


if __name__ == "__main__":
    unittest.main()
