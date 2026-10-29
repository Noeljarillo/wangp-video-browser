"""
Builders for metadata-only video containers used by the metadata tests.

They write just enough of an MP4 / MOV / Matroska file for the readers to find
the text tags (no media streams). Run directly to drop every fixture into a
folder for a manual check:  python3 tests/metadata_fixtures.py /some/tmp/dir
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FFMPEG = "/home/noel/.hermes/tools/ffmpeg-9.0.1-linux-x64/bin/ffmpeg"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------- MP4 / MOV
def box(kind, payload=b""):
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


def _ilst_item(kind, text):
    data = box(b"data", (1).to_bytes(4, "big") + b"\0\0\0\0" + text.encode("utf-8"))
    return box(kind, data)


def mp4_bytes(tags):
    """tags: {4cc bytes or freeform name str: text}. MP4 style moov/udta/meta/ilst."""
    items = b""
    for key, text in tags.items():
        if isinstance(key, bytes):
            items += _ilst_item(key, text)
        else:
            mean = box(b"mean", b"\0\0\0\0com.apple.iTunes")
            name = box(b"name", b"\0\0\0\0" + key.encode("utf-8"))
            data = box(b"data", (1).to_bytes(4, "big") + b"\0\0\0\0" + text.encode("utf-8"))
            items += box(b"----", mean + name + data)
    hdlr = box(b"hdlr", b"\0" * 8 + b"mdirappl" + b"\0" * 9)
    meta = box(b"meta", b"\0\0\0\0" + hdlr + box(b"ilst", items))
    ftyp = box(b"ftyp", b"isom\0\0\x02\0isomiso2mp41")
    return ftyp + box(b"moov", box(b"udta", meta)) + box(b"mdat", b"\0" * 16)


def mov_bytes(comment):
    """QuickTime style: moov/udta/(c)cmt with [len][lang][text]."""
    raw = comment.encode("utf-8")
    item = box(b"\xa9cmt", len(raw).to_bytes(2, "big") + b"\x15\xc7" + raw)
    ftyp = box(b"ftyp", b"qt  \0\0\x02\0qt  ")
    return ftyp + box(b"moov", box(b"udta", item)) + box(b"mdat", b"\0" * 16)


# ---------------------------------------------------------------- Matroska
def _vint_size(n):
    for length in range(1, 9):
        if n < (1 << (7 * length)) - 1:
            return ((1 << (7 * length)) | n).to_bytes(length, "big")
    raise ValueError(n)


def ebml(element_id, payload):
    return element_id.to_bytes((element_id.bit_length() + 7) // 8, "big") + _vint_size(len(payload)) + payload


def mkv_bytes(tags, doctype=b"matroska"):
    header = ebml(0x1A45DFA3, ebml(0x4282, doctype) + ebml(0x4287, b"\x04"))
    simple = b"".join(
        ebml(0x67C8, ebml(0x45A3, k.encode("utf-8")) + ebml(0x4487, v.encode("utf-8"))) for k, v in tags.items())
    info = ebml(0x1549A966, ebml(0x2AD7B1, (1000000).to_bytes(3, "big")))
    cluster = ebml(0x1F43B675, ebml(0xE7, b"\0") + b"")
    segment = ebml(0x18538067, info + cluster + ebml(0x1254C367, ebml(0x7373, ebml(0x63C0, b"") + simple)))
    return header + segment


# ---------------------------------------------------------------- payloads
WANGP_SETTINGS = {
    "prompt": "a lighthouse at dawn, waves crashing",
    "negative_prompt": "",
    "resolution": "832x480",
    "video_length": 81,
    "seed": 424242,
    "num_inference_steps": 8,
    "guidance_scale": 1,
    "sample_solver": "euler",
    "activated_loras": [],
    "loras_multipliers": "",
    "model_type": "t2v_2_2",
    "type": "WanGP v18.84 by DeepBeepMeep - Wan2.2 Text2video 14B",
    "settings_version": 2.81,
}


def comfy_vhs_comment(prompt, workflow=None):
    """VideoHelperSuite: comment = JSON {"prompt": json-string, "workflow": dict}."""
    payload = {"prompt": json.dumps(prompt)}
    if workflow is not None:
        payload["workflow"] = workflow
    return json.dumps(payload)


A1111_PARAMETERS = (
    "masterpiece, a castle on a hill <lora:detail_tweaker:0.6> <lora:film_grain>\n"
    "Negative prompt: lowres, bad anatomy\n"
    "Steps: 28, Sampler: DPM++ 2M, Schedule type: Karras, CFG scale: 7, Seed: 1234567, Size: 768x512, "
    "Model hash: 6ce0161689, Model: dreamshaper_8, Lora hashes: \"detail_tweaker: 1a2b3c, film_grain: 4d5e6f\", "
    "Version: v1.10.1"
)
FORGE_PARAMETERS = (
    "a neon city street at night, rain\n"
    "Steps: 20, Sampler: Euler, Schedule type: Simple, CFG scale: 1, Distilled CFG Scale: 3.5, Seed: 99, "
    "Size: 1024x1024, Model hash: a1b2c3, Model: flux1-dev-bnb-nf4-v2, Version: f2.0.1v1.10.1-previous-313"
)
LTX_ARGS = {
    "prompt": "a drone shot over a misty forest", "negative_prompt": "worst quality, blurry",
    "seed": 171198, "num_inference_steps": 40, "guidance_scale": 3.0, "stg_scale": 1.0,
    "height": 480, "width": 704, "num_frames": 121, "frame_rate": 25,
    "pipeline_config": "configs/ltxv-13b-0.9.7-dev.yaml",
}
HUNYUAN_ARGS = {
    "prompt": "a cat walks on the grass, realistic style", "neg_prompt": "", "seeds": [42],
    "infer_steps": 50, "cfg_scale": 1.0, "embedded_guidance_scale": 6.0, "flow_shift": 7.0,
    "video_size": [720, 1280], "video_length": 129, "flow_reverse": True,
    "dit_weight": "ckpts/hunyuan-video-t2v-720p/transformers/mp_rank_00_model_states.pt",
}


def build_all(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    files = {
        "wangp.mp4": mp4_bytes({b"\xa9cmt": json.dumps(WANGP_SETTINGS)}),
        "comfy_ksampler.mp4": mp4_bytes({b"\xa9cmt": comfy_vhs_comment(load("comfy_ksampler_prompt.json"),
                                                                      load("comfy_ui_workflow.json"))}),
        "comfy_wanvideo.mkv": mkv_bytes({"COMMENT": comfy_vhs_comment(load("comfy_wanvideo_prompt.json"))}),
        "comfy_ui_only.webm": mkv_bytes({"COMMENT": json.dumps({"workflow": load("comfy_ui_workflow.json")})},
                                        b"webm"),
        "comfy_wanvideo.mov": mov_bytes(comfy_vhs_comment(load("comfy_wanvideo_prompt.json"))),
        "comfy_separate_tags.mp4": mp4_bytes({"prompt": json.dumps(load("comfy_ksampler_prompt.json"))}),
        "reserved.mp4": mp4_bytes({b"\xa9cmt": json.dumps({"_wangp_metadata_reserved": True, "pad": " " * 64})}),
        "plain_comment.mp4": mp4_bytes({b"\xa9cmt": "just a note, not settings"}),
        "a1111.mp4": mp4_bytes({"parameters": A1111_PARAMETERS}),
        "forge.mkv": mkv_bytes({"COMMENT": FORGE_PARAMETERS}),
        "ltx.mp4": mp4_bytes({b"\xa9cmt": json.dumps(LTX_ARGS)}),
        "hunyuan.mkv": mkv_bytes({"DESCRIPTION": json.dumps(HUNYUAN_ARGS)}),
        "other_json.mp4": mp4_bytes({b"\xa9cmt": json.dumps({"foo": 1, "bar": "baz"})}),
        "no_metadata.mp4": box(b"ftyp", b"isom\0\0\x02\0isom") + box(b"mdat", b"\0" * 16),
    }
    for name, data in files.items():
        (folder / name).write_bytes(data)
    return {name: folder / name for name in files}


def ffmpeg_path():
    return FFMPEG if Path(FFMPEG).is_file() else shutil.which("ffmpeg")


def ffmpeg_clip(target, comment, extra=()):
    """Tiny real clip with `comment` set, the way VHS / WanGP write it. None without ffmpeg."""
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        return None
    meta_file = Path(target).with_suffix(".ffmeta")
    escaped = comment.replace("\\", "\\\\").replace("=", "\\=").replace(";", "\\;") \
        .replace("#", "\\#").replace("\n", "\\\n")
    meta_file.write_text(";FFMETADATA1\ncomment=" + escaped + "\n", encoding="utf-8")
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
               "color=c=gray:s=64x64:d=0.2:r=8", "-i", str(meta_file), "-map_metadata", "1",
               *extra, str(target)]
    result = subprocess.run(command, capture_output=True, timeout=60, check=False)
    meta_file.unlink(missing_ok=True)
    return Path(target) if result.returncode == 0 and Path(target).is_file() else None


if __name__ == "__main__":
    for name, path in build_all(sys.argv[1] if len(sys.argv) > 1 else "fixtures-out").items():
        print(path)
