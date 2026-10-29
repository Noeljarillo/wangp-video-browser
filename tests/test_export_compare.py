"""python3 -m unittest tests.test_export_compare  (P6.1: export comparisons)"""
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import export_compare as ec  # noqa: E402


def entry(path, seed, steps, w=832, h=480, dur=4.0, **meta):
    return {"path": str(path), "name": Path(path).name, "size": 1, "mtime": 1,
            "probe": {"width": w, "height": h, "duration": dur},
            "meta": dict({"seed": seed, "num_inference_steps": steps, "prompt": "same"}, **meta)}


class LabelTests(unittest.TestCase):
    def test_differing_keys_skip_seed_prompt(self):
        metas = [{"seed": 1, "prompt": "a", "guidance_scale": 5, "flow_shift": 3},
                 {"seed": 2, "prompt": "b", "guidance_scale": 7, "flow_shift": 3}]
        self.assertEqual(ec.differing_keys(metas), ["guidance_scale"])

    def test_labels(self):
        labels = ec.labels_for([entry("a.mp4", 42, 8, guidance_scale=5), entry("b.mp4", 43, 20, guidance_scale=7)])
        self.assertEqual(labels[0], "seed 42  |  8 steps  |  guidance_scale=5")
        self.assertIn("20 steps", labels[1])

    def test_label_falls_back_to_name(self):
        self.assertEqual(ec.labels_for([{"name": "clip.mp4", "meta": None}])[0], "clip.mp4")


class CommandTests(unittest.TestCase):
    def test_side_by_side(self):
        cmd = ec.build_video_command("ffmpeg", [entry("a.mp4", 1, 8), entry("b.mp4", 2, 8, dur=3.0)],
                                     ["l0.txt", "l1.txt"], "out.mp4", fmt="mp4", encoders={"libx264"})
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("hstack=inputs=2", graph)
        self.assertIn("drawtext=", graph)
        self.assertIn("expansion=none", graph)
        self.assertIn("libx264", cmd)
        self.assertEqual(cmd[cmd.index("-t") + 1], "3.000")
        self.assertEqual(cmd[-1], "out.mp4")

    def test_wipe_and_fallback_encoder(self):
        cmd = ec.build_video_command("ffmpeg", [entry("a.mp4", 1, 8), entry("b.mp4", 2, 8)],
                                     ["l0", "l1"], "o.webm", mode="wipe", fmt="webm", wipe=25, encoders={"libvpx"})
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("overlay=", graph)
        self.assertIn("crop=", graph)
        self.assertIn("libvpx", cmd)
        self.assertNotIn("libvpx-vp9", cmd)

    def test_gif_palette(self):
        cmd = ec.build_video_command("ffmpeg", [entry("a.mp4", 1, 8, dur=20), entry("b.mp4", 2, 8, dur=20)],
                                     ["l0", "l1"], "o.gif", fmt="gif")
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("palettegen", graph)
        self.assertTrue(graph.endswith("[out]"))
        self.assertEqual(cmd[cmd.index("-t") + 1], "8.000")

    def test_sheet(self):
        cmd = ec.build_sheet_command("ffmpeg", [entry(f"{i}.mp4", i, 8) for i in range(5)], [f"l{i}" for i in range(5)], "s.png")
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("concat=n=5", graph)
        self.assertIn("tile=4x2", graph)

    def test_filter_path_escaping(self):
        self.assertEqual(ec._esc("C:\\x\\it's"), "C\\:/x/it\\'s")


class SubmitTests(unittest.TestCase):
    def test_no_ffmpeg_is_graceful(self):
        with self.assertRaises(ec.ExportError) as ctx:
            ec.submit(None, [entry("a", 1, 8), entry("b", 2, 8)])
        self.assertIn("ffmpeg", str(ctx.exception))

    def test_validation(self):
        for kwargs, entries in (({"fmt": "avi"}, 2), ({"mode": "wipe"}, 3), ({}, 1), ({"mode": "x"}, 2)):
            with self.assertRaises(ec.ExportError):
                ec.submit("ffmpeg", [entry(f"{i}", i, 8) for i in range(entries)], **kwargs)

    def test_export_path_rejects_traversal(self):
        self.assertIsNone(ec.export_path("../server.py"))
        self.assertIsNone(ec.export_path(".hidden"))
        self.assertIsNone(ec.export_path("missing.mp4"))


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class RenderTests(unittest.TestCase):
    """End-to-end on two synthetic clips, in a temp dir (never user videos)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.old = ec.EXPORT_DIR
        ec.EXPORT_DIR = self.tmp / "exports"
        self.clips = []
        for i, color in enumerate(("red", "blue")):
            path = self.tmp / f"c{i}.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color={color}:s=160x96:d=1:r=10",
                            "-pix_fmt", "yuv420p", str(path)], check=True, timeout=60)
            self.clips.append(entry(path, i, 8, w=160, h=96, dur=1.0))

    def tearDown(self):
        ec.EXPORT_DIR = self.old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def wait(self, job):
        for _ in range(300):
            job = ec.get_job(job["id"])
            if job["status"] in ("done", "error"):
                return job
            time.sleep(0.1)
        return job

    def test_mp4_and_sheet(self):
        ffmpeg = shutil.which("ffmpeg")
        job = self.wait(ec.submit(ffmpeg, self.clips, fmt="mp4"))
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertIsNotNone(ec.export_path(job["name"]))
        again = ec.submit(ffmpeg, self.clips, fmt="mp4")
        self.assertEqual(again["status"], "done")  # cached, no re-render
        sheet = self.wait(ec.submit(ffmpeg, self.clips, kind="sheet"))
        self.assertEqual(sheet["status"], "done", sheet.get("error"))
        self.assertEqual(sorted(p.suffix for p in ec.EXPORT_DIR.iterdir()), [".mp4", ".png"])


if __name__ == "__main__":
    unittest.main()
