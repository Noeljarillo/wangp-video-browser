"""P3.1: ffmpeg frame sampling into app/.cache/frames/<key>/ (1 fps, max 32)."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from analysis import frames, gpu, jobqueue, worker  # noqa: E402

FFMPEG = shutil.which("ffmpeg")


def make_clip(path, seconds):
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=8:duration={seconds}",
                    "-pix_fmt", "yuv420p", str(path)], check=True)


class FrameRateTest(unittest.TestCase):
    def test_rate(self):
        self.assertEqual(frames.sample_rate(5), 1.0)
        self.assertEqual(frames.sample_rate(None), 1.0)
        self.assertAlmostEqual(frames.sample_rate(64), 0.5)


@unittest.skipUnless(FFMPEG, "ffmpeg not installed")
class FrameSamplingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_short_clip_one_fps_and_cached(self):
        clip = self.dir / "short.mp4"
        make_clip(clip, 5)
        before = clip.stat()
        m = frames.sample(FFMPEG, clip, self.dir / "cache", "k1", duration=5.0)
        self.assertEqual(m["count"], 5)
        self.assertEqual(m["times"][:2], [0.0, 1.0])
        self.assertTrue(all((self.dir / "cache/frames/k1" / f).is_file() for f in m["files"]))
        self.assertTrue(frames.sample(FFMPEG, clip, self.dir / "cache", "k1", duration=5.0)["cached"])
        self.assertEqual(len(frames.load(self.dir / "cache", "k1")["paths"]), 5)
        after = clip.stat()
        self.assertEqual((before.st_size, before.st_mtime_ns), (after.st_size, after.st_mtime_ns))  # C4

    def test_long_clip_capped_at_32_and_spread(self):
        clip = self.dir / "long.mp4"
        make_clip(clip, 48)
        m = frames.sample(FFMPEG, clip, self.dir / "cache", "k2", duration=48.0)
        self.assertEqual(m["count"], 32)
        self.assertGreater(m["times"][-1], 40)  # covers the whole clip, not the first 32 s

    def test_worker_runs_frames_jobs(self):
        clip = self.dir / "w.mp4"
        make_clip(clip, 3)
        db = str(self.dir / "analysis.db")
        conn = jobqueue.connect(db)
        st = clip.stat()
        jobqueue.enqueue(conn, "frames", [{"path": str(clip), "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                                           "payload": {"duration": 3.0}}])
        w = worker.Worker(db, ctx={"cache": self.dir / "cache", "ffmpeg": FFMPEG},
                          gate=gpu.Gate(detector=lambda: {"available": False}), poll=0.01)
        while w.step() == "worked":
            pass
        self.assertEqual(jobqueue.counts(conn), {"frames": {"done": 1}})
        key = jobqueue.cache_key(clip, st.st_size, st.st_mtime_ns)
        self.assertEqual(frames.load(self.dir / "cache", key)["count"], 3)
        self.assertEqual(os.listdir(self.dir / "cache" / "frames"), [key])  # no temp dirs left
        conn.close()


if __name__ == "__main__":
    unittest.main()
