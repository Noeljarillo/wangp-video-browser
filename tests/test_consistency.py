"""P3.4 / P3.5: the cosine band, the aggregation, drift detection and the core payload.

The numbers used here come from the calibration run on the real library (8 clips, CPU):
a clip scored against its own first frame landed at 70-100 (mean 93) and against another
clip's frame at 0-77 (mean 23), which is what the 0.2..0.8 band is sized for.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP / "app"))

try:
    import numpy
    from analysis import consistency

    HAVE_DEPS = True
except ImportError:
    HAVE_DEPS = False


def unit(*values):
    vec = numpy.array(values, dtype="float32")
    return (vec / numpy.linalg.norm(vec)).tolist()


@unittest.skipUnless(HAVE_DEPS, "add-on deps (numpy) not installed")
class BandTest(unittest.TestCase):
    def test_band_endpoints_and_clamping(self):
        self.assertEqual(consistency.score_from_cosine(0.2), 0.0)
        self.assertEqual(consistency.score_from_cosine(0.8), 100.0)
        self.assertEqual(consistency.score_from_cosine(0.5), 50.0)
        self.assertEqual(consistency.score_from_cosine(0.95), 100.0)   # clamped, never >100
        self.assertEqual(consistency.score_from_cosine(-0.1), 0.0)

    def test_calibration_separates_same_person_from_another(self):
        # the two clusters the real run produced: same clip ~0.72-1.0, another clip ~0.0-0.55
        self.assertGreater(consistency.score_from_cosine(0.75), 80)
        self.assertLess(consistency.score_from_cosine(0.35), 30)


@unittest.skipUnless(HAVE_DEPS, "add-on deps (numpy) not installed")
class ConsistencyTest(unittest.TestCase):
    def rows(self, per_frame):
        out = []
        for frame, vectors in per_frame.items():
            for n, vec in enumerate(vectors):
                out.append({"frame": frame, "t": frame / 10.0, "kind": "person", "score": 0.9 - n * 0.1,
                            "emb": vec})
        return out

    def test_a_clip_that_matches_its_reference_scores_high(self):
        ref = [{"name": "ref.png", "path": "/tmp/ref.png", "emb": unit(1, 0, 0)}]
        rows = self.rows({0: [unit(1, 0, 0)], 1: [unit(0.98, 0.1, 0)], 2: [unit(0.95, 0.2, 0)]})
        result, _ = consistency.consistency(rows, ref)
        self.assertGreater(result["score"], 90)
        self.assertEqual(len(result["frames"]), 3)
        self.assertEqual(result["refs"][0]["name"], "ref.png")

    def test_a_clip_that_does_not_match_scores_low(self):
        ref = [{"name": "ref.png", "path": "/tmp/ref.png", "emb": unit(1, 0, 0)}]
        rows = self.rows({0: [unit(0, 1, 0)], 1: [unit(0, 0.9, 0.2)]})
        result, _ = consistency.consistency(rows, ref)
        self.assertLess(result["score"], 10)

    def test_one_good_frame_does_not_rescue_a_mismatched_clip(self):
        ref = [{"name": "ref.png", "path": "/tmp/ref.png", "emb": unit(1, 0, 0)}]
        rows = self.rows({0: [unit(0, 1, 0)], 1: [unit(0, 1, 0)], 2: [unit(0, 1, 0)], 3: [unit(1, 0, 0)]})
        self.assertLess(consistency.consistency(rows, ref)[0]["score"], 40)

    def test_a_few_bad_frames_do_not_sink_a_matching_clip(self):
        ref = [{"name": "ref.png", "path": "/tmp/ref.png", "emb": unit(1, 0, 0)}]
        rows = self.rows({0: [unit(1, 0, 0)], 1: [unit(0.99, 0.05, 0)], 2: [unit(0.98, 0.1, 0)],
                          3: [unit(1, 0, 0)], 4: [unit(0, 1, 0)]})     # one turned-away frame
        self.assertGreater(consistency.consistency(rows, ref)[0]["score"], 90)

    def test_no_references_or_no_people_means_no_score(self):
        rows = self.rows({0: [unit(1, 0, 0)]})
        self.assertEqual(consistency.consistency(rows, [])[0], None)
        self.assertEqual(consistency.consistency([], [{"name": "r", "path": "/r", "emb": unit(1, 0, 0)}])[0], None)

    def test_face_and_person_embeddings_are_never_mixed(self):
        rows = [{"frame": 0, "kind": "person", "emb": unit(1, 0, 0)},
                {"frame": 0, "kind": "face", "emb": unit(1, 0)}]
        self.assertEqual(consistency.pick_kind(rows), "person")
        grouped = consistency._rows_by_frame(rows)
        self.assertEqual(len(grouped[0]), 1)                    # the 2-d face vector is dropped
        self.assertEqual(consistency.pick_kind([{"frame": 0, "kind": "face", "emb": unit(1, 0)}]), "face")

    def test_a_clip_with_too_few_frames_has_no_drift_verdict(self):
        result = consistency.drift(self.rows({0: [unit(1, 0, 0)]}))
        self.assertFalse(result["flagged"])
        self.assertIn("too few", result["note"])


@unittest.skipUnless(HAVE_DEPS, "add-on deps (numpy) not installed")
class DriftTest(unittest.TestCase):
    def test_stable_identity_is_not_flagged(self):
        rows = [{"frame": f, "kind": "person", "score": 0.9, "emb": unit(1, 0.02 * f, 0)} for f in range(10)]
        result = consistency.drift(rows)
        self.assertFalse(result["flagged"])
        self.assertLess(result["drop"], consistency.DRIFT_DROP)

    def test_identity_flip_is_flagged_and_names_the_worst_frame(self):
        rows = [{"frame": f, "kind": "person", "score": 0.9, "emb": unit(1, 0.02 * f, 0)} for f in range(5)]
        rows += [{"frame": f, "kind": "person", "score": 0.9, "emb": unit(0, 0.05, 1)} for f in range(5, 10)]
        result = consistency.drift(rows)
        self.assertTrue(result["flagged"])
        self.assertGreaterEqual(result["drop"], consistency.DRIFT_DROP)
        self.assertGreaterEqual(result["worst_frame"], 5)


class CorePayloadTest(unittest.TestCase):
    def test_payload_adds_the_band_and_keeps_unknown_clips_out(self):
        import consistency_host

        tmp = Path(tempfile.mkdtemp(prefix="cons-"))
        try:
            (tmp / "a.json").write_text(json.dumps({
                "path": "/v/a.mp4", "score": 82.5, "frames": [], "refs": [{"name": "r.png", "score": 90}],
                "drift": {"flagged": True, "drop": 0.4, "frames": []}}), encoding="utf-8")
            body = consistency_host.payload([{"id": "1", "path": "/v/a.mp4"}, {"id": "2", "path": "/v/b.mp4"}],
                                            folder=tmp)
            self.assertEqual(list(body["clips"]), ["1"])
            self.assertEqual(body["clips"]["1"]["band"], "High")
            self.assertTrue(body["clips"]["1"]["drift"])
            self.assertEqual([b["key"] for b in body["bands"]], ["High", "Mixed", "Low"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
