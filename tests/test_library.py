import os
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import library  # noqa: E402


class LibraryStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.store = self.dir / ".data" / "library.json"
        library.reset_cache()

    def tearDown(self):
        library.reset_cache()
        self.tmp.cleanup()

    def test_content_id_survives_rename(self):
        clip = self.dir / "a.mp4"
        clip.write_bytes(b"x" * (2 * 1024 * 1024))
        cid = library.content_id(clip)
        renamed = self.dir / "renamed.mp4"
        clip.rename(renamed)
        self.assertEqual(cid, library.content_id(renamed))
        # same head, different size -> different id
        renamed.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
        self.assertNotEqual(cid, library.content_id(renamed))

    def test_update_persists_and_reloads(self):
        library.update(["c1", "c2"], {"rating": 4, "status": "keep", "tags": [" hero ", "hero", "night"]}, self.store)
        library.update(["c2"], {"collections": ["Best of"], "status": None}, self.store)
        library.reset_cache()  # simulate a restart
        self.assertEqual(library.get("c1", self.store)["tags"], ["hero", "night"])
        self.assertEqual(library.get("c1", self.store)["status"], "keep")
        c2 = library.get("c2", self.store)
        self.assertNotIn("status", c2)
        self.assertEqual(c2["collections"], ["Best of"])
        library.update(["c1"], {"rating": 0, "status": None, "tags": []}, self.store)
        self.assertEqual(library.get("c1", self.store), {})
        self.assertEqual([p.name for p in self.store.parent.iterdir()], ["library.json"])  # no tmp left

    def test_rejects_bad_values(self):
        for patch in ({"rating": 6}, {"rating": True}, {"status": "maybe"}, "nope"):
            with self.assertRaises(ValueError):
                library.update(["c1"], patch, self.store)

    def test_corrupt_store_falls_back_to_empty(self):
        self.store.parent.mkdir(parents=True)
        self.store.write_text("{not json", encoding="utf-8")
        self.assertEqual(library.load(self.store)["items"], {})

    def test_trash_freedesktop_on_temp_file(self):
        victim = self.dir / "clips" / "reject me.mp4"
        victim.parent.mkdir()
        victim.write_bytes(b"temp")
        twin = self.dir / "clips2" / "reject me.mp4"
        twin.parent.mkdir()
        twin.write_bytes(b"temp2")
        trash = self.dir / "Trash"
        library.move_to_trash(victim, trash_dir=trash)
        library.move_to_trash(twin, trash_dir=trash)
        self.assertFalse(victim.exists())
        names = sorted(p.name for p in (trash / "files").iterdir())
        self.assertEqual(names, ["reject me.2.mp4", "reject me.mp4"])
        info = (trash / "info" / "reject me.mp4.trashinfo").read_text(encoding="utf-8").splitlines()
        self.assertEqual(info[0], "[Trash Info]")
        self.assertEqual(unquote(info[1][len("Path="):]), str(victim.resolve()))
        self.assertTrue(info[2].startswith("DeletionDate="))
        with self.assertRaises(OSError):
            library.move_to_trash(victim, trash_dir=trash)  # already gone


if __name__ == "__main__":
    unittest.main()
