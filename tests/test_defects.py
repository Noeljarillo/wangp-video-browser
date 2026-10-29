"""P5.1 defect flags: the measurements, the thresholds and the flag rules.

Runs on the core interpreter (stdlib unittest); the parts that need numpy or ffmpeg
skip cleanly when the add-on environment is absent. Synthetic clips are built with
ffmpeg in a temp dir so the detectors are proven to fire, not just to stay quiet.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "app"))  # core modules (defects_host) live in app/

FFMPEG = os.environ.get("WANGP_FFMPEG") or shutil.which("ffmpeg") or shutil.which("ffmpeg", path=os.path.expanduser("~/.hermes/tools/ffmpeg-9.0.1-linux-x64/bin"))

try:
    import numpy  # noqa: F401
    from analysis import defects

    HAVE_DEPS = True
except ImportError:  # core venv without the add-on deps
    HAVE_DEPS = False


def make_clip(path, kind):
    """A 3 s 320x180 clip at 10 fps: 'black', 'frozen' (still frame) or 'blur'."""
    if kind == "black":
        cmd = [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=320x180:d=3:r=10", str(path)]
    else:
        src = [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:duration=3:rate=10"]
        if kind == "frozen":
            cmd = src + ["-vf", "trim=end_frame=1,loop=loop=29:size=1:start=0", "-t", "3", str(path)]
        else:
            cmd = src + ["-vf", "boxblur=20:5", str(path)]
    subprocess.run(cmd, check=True, capture_output=True)


@unittest.skipUnless(HAVE_DEPS, "add-on deps (numpy) not installed")
class GreyStatsTest(unittest.TestCase):
    def test_luma_and_diff_maths(self):
        seq = numpy.array([[[0] * 4] * 4, [[10] * 4] * 4, [[10] * 4] * 4], dtype="uint8")
        out = defects.grey_stats(seq, 2.0)
        self.assertEqual(out["n"], 3)
        self.assertAlmostEqual(out["luma_mean"], 6.67, places=2)
        # one identical pair for ~1 s at 2 fps -> a frozen run of >= 0.5 s
        self.assertGreaterEqual(out["frozen_longest_s"], 0.5)
        self.assertIn("frozen", out["flags"])

    def test_black_and_blown(self):
        self.assertIn("black", defects.grey_stats(numpy.zeros((5, 4, 4), dtype="uint8"), 5.0)["flags"])
        self.assertIn("blown", defects.grey_stats(numpy.full((20, 4, 4), 255, dtype="uint8"), 5.0)["flags"])

    def test_jitter_threshold_is_measured_not_guessed(self):
        # a small step is normal motion; a large alternating jump is jitter
        calm = numpy.array([[[i * 2] * 4] * 4 for i in range(6)], dtype="uint8")
        jumpy = numpy.array([[[0] * 4] * 4, [[200] * 4] * 4] * 3, dtype="uint8")
        self.assertLess(defects.grey_stats(calm, 6.0)["jitter"], defects.JITTER_HIGH)
        self.assertGreater(defects.grey_stats(jumpy, 6.0)["jitter"], defects.JITTER_HIGH)

    def test_flicker_needs_many_spikes(self):
        flat = numpy.full((40, 4, 4), 120, dtype="uint8")
        flick = numpy.full((40, 4, 4), 120, dtype="uint8")
        for i in range(0, 40, 4):
            flick[i] = 30  # every 4th grey frame drops -> spikes, not motion
        self.assertNotIn("flicker", defects.grey_stats(flat, 10.0)["flags"])
        self.assertIn("flicker", defects.grey_stats(flick, 10.0)["flags"])


@unittest.skipUnless(HAVE_DEPS and FFMPEG, "needs the add-on deps and ffmpeg")
class SyntheticClipsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="defects-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def analyse(self, kind):
        clip = self.tmp / f"{kind}.mp4"
        make_clip(clip, kind)
        return defects.analyse(FFMPEG, self.tmp, kind, clip)

    def test_black_clip_is_flagged(self):
        self.assertIn("black", self.analyse("black")["flags"])

    def test_frozen_clip_is_flagged(self):
        result = self.analyse("frozen")
        self.assertIn("frozen", result["flags"])
        self.assertGreaterEqual(result["luma"]["frozen_longest_s"], 1.0)

    def test_blurred_clip_is_soft(self):
        # boxblur=20 over a moving test pattern: sharpness collapses, so the Soft flag fires
        self.assertIn("blur", self.analyse("blur")["flags"])

    def test_result_is_cached_by_key(self):
        clip = self.tmp / "frozen.mp4"
        make_clip(clip, "frozen")
        first = defects.analyse(FFMPEG, self.tmp, "k1", clip)
        defects.save(self.tmp, "k1", first)
        self.assertEqual(defects.load(self.tmp, "k1")["flags"], first["flags"])
        self.assertEqual(defects.load(self.tmp, "missing"), None)


class HostPayloadTest(unittest.TestCase):
    def test_payload_maps_paths_to_ids_and_hides_unknowns(self):
        import defects_host

        tmp = Path(tempfile.mkdtemp(prefix="defects-host-"))
        try:
            (tmp / "a.json").write_text(json.dumps({"path": "/v/a.mp4", "flags": ["flicker"], "aesthetic": 5.1,
                                                    "luma": {"jitter": 4.2}, "sharpness": None}), encoding="utf-8")
            body = defects_host.payload([{"id": "1", "path": "/v/a.mp4"}, {"id": "2", "path": "/v/b.mp4"}], folder=tmp)
            self.assertEqual(list(body["clips"]), ["1"])
            self.assertEqual(body["clips"]["1"]["flags"], ["flicker"])
            self.assertEqual([f["key"] for f in body["flags"]][0], "flicker")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
