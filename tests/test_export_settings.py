import json
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import export_settings as ex  # noqa: E402

META = {
    "_source": "wangp", "_comfy": None, "type": "WanGP v18.888 by DeepBeepMeep - MiniMax H3",
    "model_type": "minimax_h3_ref2va", "model_filename": "https://x/y.safetensors",
    "prompt": "a cat", "seed": 145279253, "num_inference_steps": 15, "resolution": "1280x704",
    "video_length": 209, "settings_version": 2.82, "activated_loras": [], "loras_multipliers": "",
    "generation_time": 812, "creation_date": "2026-10-29T22:22:15", "creation_timestamp": 1,
    "output_filename": "x.mp4", "output_role": "final",
}


class ExportSettingsTest(unittest.TestCase):
    def test_shape_matches_wangp_settings(self):
        settings = ex.build(META)
        self.assertFalse([k for k in settings if k.startswith("_")])
        for key in ex.RUN_ONLY_KEYS:
            self.assertNotIn(key, settings)
        # What WanGP's loader keys on: model id + "WanGP" in type + the recipe itself.
        self.assertEqual(settings["model_type"], "minimax_h3_ref2va")
        self.assertIn("WanGP", settings["type"])
        self.assertEqual(settings["seed"], 145279253)
        self.assertEqual(settings["settings_version"], 2.82)

    def test_new_seed(self):
        settings = ex.build(META, new_seed=True, rng=random.Random(1))
        self.assertNotEqual(settings["seed"], META["seed"])
        self.assertTrue(0 <= settings["seed"] <= ex.MAX_SEED)
        self.assertEqual(META["seed"], 145279253)  # source untouched

    def test_non_wangp_refused(self):
        for meta in ({}, {"_source": "comfyui", "seed": 1}, {"_source": "wangp", "prompt": "no model"}):
            with self.assertRaises(ex.NotExportable):
                ex.build(meta)

    def test_export_bytes_and_filename(self):
        entry = {"meta": META, "filename_info": {"date": "2026-10-29", "time": "22:22:12"}}
        body, name = ex.export(entry)
        self.assertEqual(json.loads(body)["prompt"], "a cat")
        self.assertEqual(name, "minimax_h3_ref2va_2026-10-29-222212_seed145279253.json")


if __name__ == "__main__":
    unittest.main()
