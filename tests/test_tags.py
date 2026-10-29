"""P4.2 auto-tags: vocabulary (stdlib-parsable), core payload, and (with numpy/cv2) flow classification."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

import tags_host  # noqa: E402

try:
    import cv2
    import numpy as np
except ImportError:  # system python without the add-on
    cv2 = np = None


class VocabTests(unittest.TestCase):
    def test_tags_yaml_is_json_and_has_required_groups(self):
        groups = tags_host.vocabulary()
        ids = [g["id"] for g in groups]
        self.assertEqual(ids, ["shot", "place", "time", "style", "motion"])
        motion = groups[-1]["labels"]
        self.assertEqual(motion, ["static", "pan", "tilt", "zoom", "orbit"])
        self.assertIn("night", groups[2]["labels"])
        self.assertIn("indoor", groups[1]["labels"])

    def test_missing_vocab_is_empty(self):
        self.assertEqual(tags_host.vocabulary("/nonexistent/tags.yaml"), [])


class PayloadTests(unittest.TestCase):
    def test_maps_paths_to_ids_and_rereads_on_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "k1.json").write_text(json.dumps({"path": "/v/a.mp4", "tags": {"time": "night"}}))
            (folder / "bad.json").write_text("{")
            entries = [{"id": "A", "path": "/v/a.mp4"}, {"id": "B", "path": "/v/b.mp4"}]
            out = tags_host.payload(entries, folder=folder)
            self.assertEqual(out["tags"], {"A": {"time": "night"}})
            self.assertTrue(out["groups"])
            (folder / "k2.json").write_text(json.dumps({"path": "/v/b.mp4", "tags": {"motion": "pan"}}))
            self.assertEqual(tags_host.payload(entries, folder=folder)["tags"]["B"], {"motion": "pan"})

    def test_absent_folder(self):
        self.assertEqual(tags_host.payload([{"id": "A", "path": "/x"}], folder="/nonexistent")["tags"], {})


@unittest.skipIf(cv2 is None, "opencv/numpy not installed (analysis add-on venv only)")
class MotionTests(unittest.TestCase):
    def setUp(self):
        from analysis import tags
        self.tags = tags
        self.cfg = tags.load_vocab()["motion"]
        rng = np.random.default_rng(1)
        self.base = cv2.GaussianBlur((rng.random((400, 600)) * 255).astype(np.uint8), (7, 7), 2)

    def _view(self, img, dx=0.0, dy=0.0, scale=1.0):
        m = np.float32([[scale, 0, (1 - scale) * 300 + dx], [0, scale, (1 - scale) * 200 + dy]])
        return cv2.warpAffine(img, m, (600, 400))[50:350, 75:525]

    def _label(self, a, b):
        a, b = self.tags._gray(a, 256), self.tags._gray(b, 256)
        flow = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        return self.tags.classify_flow(flow, self.cfg)[0]

    def test_static_pan_tilt_zoom(self):
        a = self._view(self.base)
        self.assertEqual(self._label(a, self._view(self.base)), "static")
        self.assertEqual(self._label(a, self._view(self.base, dx=12)), "pan")
        self.assertEqual(self._label(a, self._view(self.base, dy=10)), "tilt")
        self.assertEqual(self._label(a, self._view(self.base, scale=1.06)), "zoom")

    def test_orbit_subject_still_background_moves(self):
        a, b = self._view(self.base), self._view(self.base, dx=12)
        h, w = a.shape
        y0, y1, x0, x1 = int(h * 0.25), int(h * 0.75), int(w * 0.33), int(w * 0.67)
        b = b.copy()
        b[y0:y1, x0:x1] = a[y0:y1, x0:x1]  # subject stays put, background slides
        self.assertEqual(self._label(a, b), "orbit")

    def test_zero_shot_picks_best_label(self):
        text = {"time": (["day", "night"], np.eye(2, 8, dtype=np.float32))}
        frames = np.zeros((3, 8), np.float16)
        frames[:, 1] = 1
        tags, scores = self.tags.zero_shot(frames, text, 10.0, -5.0)
        self.assertEqual(tags, {"time": "night"})
        self.assertGreater(scores["time"]["night"], scores["time"]["day"])


if __name__ == "__main__":
    unittest.main()
