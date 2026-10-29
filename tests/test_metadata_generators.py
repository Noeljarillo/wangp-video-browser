import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "app"))

import metadata  # noqa: E402
import metadata_fixtures as fx  # noqa: E402


class OtherGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.files = fx.build_all(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def read(self, name):
        return metadata.read_video_metadata(self.files[name], None)

    def check(self, meta, expected):
        for key, value in expected.items():
            self.assertEqual(meta.get(key), value, key)

    def test_a1111_parameters(self):
        self.check(self.read("a1111.mp4"), {
            "_source": "a1111", "prompt": "masterpiece, a castle on a hill <lora:detail_tweaker:0.6> <lora:film_grain>",
            "negative_prompt": "lowres, bad anatomy", "num_inference_steps": 28, "sample_solver": "DPM++ 2M",
            "scheduler": "Karras", "guidance_scale": 7, "seed": 1234567, "resolution": "768x512",
            "model_type": "dreamshaper_8", "model_hash": "6ce0161689",
            "lora_hashes": "detail_tweaker: 1a2b3c, film_grain: 4d5e6f",
            "activated_loras": ["detail_tweaker", "film_grain"], "loras_multipliers": "0.6 1",
        })

    def test_forge_parameters_mkv(self):
        self.check(self.read("forge.mkv"), {
            "_source": "forge", "prompt": "a neon city street at night, rain", "seed": 99,
            "num_inference_steps": 20, "sample_solver": "Euler", "guidance_scale": 1,
            "embedded_guidance_scale": 3.5, "resolution": "1024x1024", "model_type": "flux1-dev-bnb-nf4-v2",
            "activated_loras": [],
        })
        self.assertNotIn("negative_prompt", self.read("forge.mkv"))

    def test_ltx_video_args(self):
        self.check(self.read("ltx.mp4"), {
            "_source": "ltx-video", "prompt": "a drone shot over a misty forest",
            "negative_prompt": "worst quality, blurry", "seed": 171198, "num_inference_steps": 40,
            "guidance_scale": 3, "resolution": "704x480", "video_length": 121,
            "model_type": "ltxv-13b-0.9.7-dev.yaml", "stg_scale": 1, "frame_rate": 25,
        })

    def test_hunyuan_args(self):
        meta = self.read("hunyuan.mkv")
        self.check(meta, {
            "_source": "hunyuan", "prompt": "a cat walks on the grass, realistic style", "seed": 42,
            "num_inference_steps": 50, "guidance_scale": 1, "embedded_guidance_scale": 6.0,
            "flow_shift": 7, "resolution": "1280x720", "video_length": 129,
            "model_type": "mp_rank_00_model_states",
        })
        for alias in ("seeds", "infer_steps", "cfg_scale", "video_size", "neg_prompt", "dit_weight"):
            self.assertNotIn(alias, meta)

    def test_unrecognised_json_and_text_unchanged(self):
        self.assertEqual(self.read("other_json.mp4"), {"foo": 1, "bar": "baz", "_source": "unknown"})
        self.assertEqual(self.read("plain_comment.mp4"), {})
        self.assertIsNone(metadata.parse_a1111("Steps are described here, no params"))

    def test_wangp_still_wins(self):
        self.assertEqual(self.read("wangp.mp4")["_source"], "wangp")


if __name__ == "__main__":
    unittest.main()
