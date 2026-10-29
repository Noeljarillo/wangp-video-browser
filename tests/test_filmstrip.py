import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import filmstrip  # noqa: E402

FFMPEG = shutil.which("ffmpeg")


def wait_ready(strips, entry, seconds=30):
    end = time.time() + seconds
    while time.time() < end:
        status, path = strips.status(entry)
        if status != "queued":
            return status, path
        time.sleep(0.1)
    return "timeout", None


class FilmstripTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.clip = self.dir / "clip.mp4"
        self.clip.write_bytes(b"not really a video")
        st = self.clip.stat()
        self.entry = {"path": str(self.clip), "size": st.st_size, "mtime": st.st_mtime, "probe": {"duration": 4.0}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_ffmpeg_falls_back(self):
        strips = filmstrip.Filmstrips(self.dir / "cache", None)
        self.assertEqual(strips.status(self.entry), ("unavailable", None))

    def test_frame_times_and_command(self):
        self.assertEqual(filmstrip.frame_times(8.0), [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5])
        self.assertEqual(filmstrip.frame_times(0), [])
        cmd = filmstrip.build_command("ffmpeg", "in.mp4", "out.jpg", 4.0)
        self.assertIn("fps=8/4.000,scale=160:-2,tile=8x1", cmd)

    def test_cache_key_follows_size_and_mtime(self):
        strips = filmstrip.Filmstrips(self.dir / "cache", None)
        a = strips.key(self.entry)
        self.assertEqual(a, strips.key(dict(self.entry)))
        self.assertNotEqual(a, strips.key(dict(self.entry, mtime=self.entry["mtime"] + 1)))
        self.assertNotEqual(a, strips.key(dict(self.entry, size=1)))

    def test_queue_never_blocks_and_failure_is_remembered(self):
        fake = self.dir / "slowfail.sh"
        fake.write_text("#!/bin/sh\nsleep 0.5\nexit 1\n")
        fake.chmod(0o755)
        strips = filmstrip.Filmstrips(self.dir / "cache", str(fake))
        start = time.time()
        self.assertEqual(strips.status(self.entry)[0], "queued")
        self.assertLess(time.time() - start, 0.2)
        self.assertEqual(wait_ready(strips, self.entry)[0], "unavailable")

    @unittest.skipUnless(FFMPEG, "ffmpeg not installed")
    def test_real_sprite_is_cached(self):
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=16",
                        "-t", "2", "-pix_fmt", "yuv420p", str(self.clip)], check=True)
        st = self.clip.stat()
        entry = {"path": str(self.clip), "size": st.st_size, "mtime": st.st_mtime, "probe": {"duration": 2.0}}
        strips = filmstrip.Filmstrips(self.dir / "cache", FFMPEG)
        status, path = wait_ready(strips, entry)
        self.assertEqual(status, "ready")
        data = path.read_bytes()
        self.assertEqual(data[:2], b"\xff\xd8")
        # 8 frames of 160px side by side.
        out = subprocess.run([FFMPEG, "-i", str(path)], capture_output=True, text=True).stderr
        self.assertIn("1280x90", out)
        before = path.stat().st_mtime_ns
        self.assertEqual(strips.status(entry), ("ready", path))
        self.assertEqual(path.stat().st_mtime_ns, before)


if __name__ == "__main__":
    unittest.main()
