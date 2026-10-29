import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "app"))

import metadata  # noqa: E402
import metadata_fixtures as fx  # noqa: E402


class MetadataFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.files = fx.build_all(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def read(self, name):
        # ffprobe=None: the pure-python readers alone must find everything.
        return metadata.read_video_metadata(self.files[name], None)

    def test_wangp_clip_unchanged(self):
        meta = self.read("wangp.mp4")
        self.assertEqual(meta.pop("_source"), "wangp")
        self.assertEqual(meta, fx.WANGP_SETTINGS)

    def test_comfy_ksampler_workflow(self):
        meta = self.read("comfy_ksampler.mp4")
        self.assertEqual(meta["_source"], "comfyui")
        expected = {
            "seed": 123456789, "num_inference_steps": 30, "guidance_scale": 6, "sample_solver": "uni_pc",
            "scheduler": "simple", "resolution": "832x480", "video_length": 33, "flow_shift": 8,
            "prompt": "a red fox running through fresh snow, cinematic",
            "negative_prompt": "blurry, low quality, watermark",
            "activated_loras": ["detail_boost.safetensors", "wan_watercolor.safetensors"],
            "loras_multipliers": "1 0.8", "model_type": "wan2.1_t2v_14B_fp8_e4m3fn",
        }
        for key, value in expected.items():
            self.assertEqual(meta.get(key), value, key)
        self.assertEqual(meta["_comfy"]["prompt"], fx.load("comfy_ksampler_prompt.json"))
        self.assertEqual(meta["_comfy"]["workflow"], fx.load("comfy_ui_workflow.json"))

    def test_comfy_wanvideo_workflow_mkv(self):
        meta = self.read("comfy_wanvideo.mkv")
        self.assertEqual(meta["_source"], "comfyui")
        expected = {
            "seed": 42, "num_inference_steps": 25, "guidance_scale": 6, "sample_solver": "unipc",
            "scheduler": "unipc", "flow_shift": 5, "resolution": "1280x720", "video_length": 81,
            "prompt": "a tabby cat surfing a wave at sunset",
            "negative_prompt": "static, overexposed, bad hands",
            "activated_loras": ["motion_smooth.safetensors", "Wan21_CausVid_14B_T2V_lora_rank32.safetensors"],
            "loras_multipliers": "1 0.5", "model_type": "Wan2_1-T2V-14B_fp8_e4m3fn",
        }
        for key, value in expected.items():
            self.assertEqual(meta.get(key), value, key)

    def test_comfy_wanvideo_quicktime_mov(self):
        meta = self.read("comfy_wanvideo.mov")
        self.assertEqual((meta["_source"], meta["seed"], meta["resolution"]), ("comfyui", 42, "1280x720"))

    def test_comfy_ui_workflow_only(self):
        meta = self.read("comfy_ui_only.webm")
        self.assertEqual(meta["_source"], "comfyui")
        self.assertEqual((meta["seed"], meta["num_inference_steps"], meta["guidance_scale"],
                          meta["sample_solver"], meta["resolution"], meta["model_type"]),
                         (987654, 20, 7.5, "euler", "1024x576", "sd_xl_base_1.0"))
        self.assertEqual((meta["prompt"], meta["negative_prompt"]), ("a lighthouse in a storm", "text, watermark"))
        self.assertIsNone(meta["_comfy"]["prompt"])

    def test_comfy_separate_prompt_tag(self):
        meta = self.read("comfy_separate_tags.mp4")
        self.assertEqual((meta["_source"], meta["seed"]), ("comfyui", 123456789))

    def test_unknown_files_unchanged(self):
        self.assertEqual(self.read("no_metadata.mp4"), {})
        self.assertEqual(self.read("plain_comment.mp4"), {})
        self.assertEqual(self.read("reserved.mp4"), {})

    def test_meta_is_json_serialisable(self):
        for name in self.files:
            json.dumps(self.read(name))

    def test_garbage_does_not_raise(self):
        path = Path(self.tmp.name) / "garbage.mkv"
        path.write_bytes(b"\x1aE\xdf\xa3\xff\xff\xff" + bytes(range(256)) * 4)
        self.assertEqual(metadata.read_video_metadata(path, None), {})
        path = Path(self.tmp.name) / "garbage.mp4"
        path.write_bytes(b"\0\0\0\x10moov\0\0\0\xffudta" + bytes(range(256)))
        self.assertEqual(metadata.read_video_metadata(path, None), {})


@unittest.skipUnless(fx.ffmpeg_path(), "ffmpeg not available")
class FfmpegClipTests(unittest.TestCase):
    """Real (tiny) clips written by ffmpeg the way VideoHelperSuite does it."""

    def test_vhs_style_clips(self):
        comment = fx.comfy_vhs_comment(fx.load("comfy_ksampler_prompt.json"), fx.load("comfy_ui_workflow.json"))
        with tempfile.TemporaryDirectory() as tmp:
            for ext, extra in ((".mp4", ("-c:v", "mpeg4")), (".mkv", ("-c:v", "mpeg4")),
                               (".mov", ("-c:v", "mpeg4")), (".webm", ("-c:v", "libvpx")) ):
                clip = fx.ffmpeg_clip(Path(tmp) / f"clip{ext}", comment, extra)
                if clip is None:
                    continue  # encoder missing in this ffmpeg build
                with self.subTest(ext=ext):
                    meta = metadata.read_video_metadata(clip, None)
                    self.assertEqual(meta.get("_source"), "comfyui")
                    self.assertEqual(meta.get("seed"), 123456789)
                    self.assertEqual(meta.get("resolution"), "832x480")


if __name__ == "__main__":
    unittest.main()
