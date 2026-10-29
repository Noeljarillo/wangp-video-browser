import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import watcher  # noqa: E402


class FolderWatcherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        os.makedirs(os.path.join(self.root, "sub"))
        Path(self.root, "old.mp4").write_bytes(b"x")
        self.changes = []
        self.w = watcher.FolderWatcher(lambda: [self.root], lambda a, r: self.changes.append((a, r)),
                                       (".mp4",), {".cache"})
        self.w.tick()  # baseline

    def tearDown(self):
        self.tmp.cleanup()

    def bump(self, path):
        # Directory mtime granularity can be coarse; force a visible change.
        t = time.time() + len(self.changes) + 5
        os.utime(path, (t, t))

    def test_baseline_reports_nothing(self):
        self.assertEqual(self.w.tick(), ([], []))

    def test_new_file_reported_once_settled(self):
        target = os.path.join(self.root, "sub", "new.mp4")
        Path(target).write_bytes(b"data")
        Path(self.root, "sub", "note.txt").write_text("x")
        self.bump(os.path.join(self.root, "sub"))
        self.assertEqual(self.w.tick(), ([], []))           # first seen: pending
        added, removed = self.w.tick()                     # unchanged: settled
        self.assertEqual(added, [(target, self.root)])
        self.assertEqual(self.w.tick(), ([], []))

    def test_growing_file_waits(self):
        target = os.path.join(self.root, "grow.mp4")
        Path(target).write_bytes(b"a")
        self.bump(self.root)
        self.w.tick()
        with open(target, "ab") as h:
            h.write(b"more")
        self.assertEqual(self.w.tick()[0], [])
        self.assertEqual(self.w.tick()[0], [(target, self.root)])

    def test_removed_file_and_dir(self):
        os.remove(os.path.join(self.root, "old.mp4"))
        self.bump(self.root)
        self.assertEqual(self.w.tick(), ([], [os.path.join(self.root, "old.mp4")]))

    def test_skips_hidden_and_skip_dirs(self):
        for d in (".cache", ".hidden"):
            os.makedirs(os.path.join(self.root, d))
            Path(self.root, d, "x.mp4").write_bytes(b"x")
        self.bump(self.root)
        self.w.tick()
        self.assertEqual(self.w.tick(), ([], []))

    def test_root_change_rebaselines(self):
        other = tempfile.mkdtemp()
        Path(other, "a.mp4").write_bytes(b"x")
        self.w.roots_fn = lambda: [self.root, other]
        self.assertEqual(self.w.tick(), ([], []))
        self.assertEqual(self.w.tick(), ([], []))


class EventHubTest(unittest.TestCase):
    def test_fanout_and_full_queue(self):
        hub = watcher.EventHub(backlog=1)
        a, b = hub.subscribe(), hub.subscribe()
        hub.publish({"n": 1})
        hub.publish({"n": 2})  # dropped for full queues, never blocks
        self.assertEqual(a.get_nowait(), '{"n": 1}')
        self.assertEqual(b.get_nowait(), '{"n": 1}')
        hub.unsubscribe(a)
        self.assertEqual(hub.count(), 1)


if __name__ == "__main__":
    unittest.main()
