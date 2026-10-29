"""P5.1 defect flags: real per-clip measurements, no guessing.

Two cheap passes per clip:
  * one ffmpeg pass at 32x18 grey (<= 10 fps) -> luma curve + frame-diff energy.
    Gives flicker (luma spikes), frozen runs (identical frames), black / blown-out
    frames and the temporal-jitter score.
  * the P3.1 sampled frames (cv2) -> Laplacian-variance sharpness per frame, and the
    aesthetic score of the sharpest frame when the LAION predictor is installed.

Result per clip in app/.cache/defects/<key>.json:
    {"path", "flags": [...], "luma": {...}, "sharpness": {...}, "aesthetic": float|None,
     "frames": {...}, "ms": int, "version": 1}
Flags are plain names the UI filters on:
    flicker, frozen, black, blown, jitter, blur, low_aesthetic
The source video is only read (C4).
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from analysis import frames

VERSION = 2
GREY = (64, 36)          # width, height of the luma pass (small enough to be cheap,
                         # big enough that two different frames are not bit-identical)
MAX_GREY_FPS = 10.0
# Thresholds (measured on the dev library, documented in docs/DEFECTS.md).
FLICKER_SPIKE = 3.5      # robust z of |d_luma| over its own median
FROZEN_RUN_S = 0.5       # identical frames for longer than this = frozen
BLACK_LUMA = 16.0        # 0..255
BLOWN_LUMA = 240.0
# jitter = median grey-level change between frames. Dev library (32 reference-to-video
# clips, all moving) measured 0.5 .. 25.0 with a median of 9.4, so the flag sits at 2x the
# median: slow motion is normal here, a clip that changes 19+ grey levels per tick is not.
JITTER_HIGH = 19.0
BLUR_LAP = 45.0          # median Laplacian variance across sampled frames
LOW_AESTHETIC = 4.0      # LAION predictor is 1..10


def defects_dir(cache_dir):
    return Path(cache_dir) / "defects"


def result_path(cache_dir, key):
    return defects_dir(cache_dir) / f"{key}.json"


def luma_pass(ffmpeg, path, fps=None):
    """Decode the whole clip at GREY size into a (n, h, w) uint8 array.

    Returns (frames, eff_fps). One decode, no temp files.
    """
    w, h = GREY
    eff = min(float(fps or MAX_GREY_FPS), MAX_GREY_FPS)
    eff = max(eff, 1.0)
    cmd = [str(ffmpeg), "-v", "error", "-i", str(path), "-an", "-sn", "-dn",
           "-vf", f"fps={eff:.4f},scale={w}:{h}:flags=area,format=gray",
           "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    proc = subprocess.run(cmd, capture_output=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[-300:] or "ffmpeg failed")
    buf = np.frombuffer(proc.stdout, dtype=np.uint8)
    if buf.size < w * h:
        return np.zeros((0, h, w), dtype=np.uint8), eff
    return buf[: buf.size - buf.size % (w * h)].reshape(-1, h, w), eff


def grey_stats(seq, fps):
    """Luma curve, frame-diff energy, frozen runs, black / blown / jitter flags."""
    out = {"fps": round(fps, 3), "n": int(len(seq)), "flags": []}
    if len(seq) < 2:
        return out
    lo = seq.astype(np.float32)
    luma = lo.reshape(len(seq), -1).mean(axis=1)
    diff = np.abs(np.diff(lo, axis=0)).reshape(len(seq) - 1, -1).mean(axis=1)
    dluma = np.abs(np.diff(luma))
    med_d = float(np.median(dluma)) if dluma.size else 0.0
    mad = float(np.median(np.abs(dluma - med_d))) or 1e-3
    spikes = int((dluma > med_d + FLICKER_SPIKE * 1.4826 * mad).sum()) if med_d >= 0 else 0
    # "identical" tolerates one grey level of encoder noise, which a re-encode of the same
    # frame always adds; two different frames of a real clip differ by tens of levels.
    identical = (np.abs(np.diff(lo, axis=0)).max(axis=(1, 2)) <= 1.0)
    runs, cur = [], 0
    for same in identical:
        cur = cur + 1 if same else 0
        runs.append(cur)
    longest = (max(runs) + 1) / fps if runs else 0.0
    # Jitter is the median per-tick change in grey levels (0..255). Dividing by the
    # clip's own luma inflated dark clips (a 2-level step on a near-black frame read as
    # 40 %), so the absolute measure is used and the threshold is measured on the library.
    jitter = float(np.median(diff))
    out.update({
        "luma_mean": round(float(luma.mean()), 2),
        "luma_min": round(float(luma.min()), 2),
        "luma_max": round(float(luma.max()), 2),
        "flicker_spikes": spikes,
        "flicker_z": round(float(med_d / (mad * 1.4826)), 2),
        "frozen_longest_s": round(longest, 2),
        "jitter": round(jitter, 2),
        "black_frames": int((luma < BLACK_LUMA).sum()),
        "blown_frames": int((luma > BLOWN_LUMA).sum()),
        "identical_pairs": int(identical.sum()),
    })
    # spikes counted on |d luma|; a stable clip keeps a handful, a flickering one many
    if spikes >= max(6, len(luma) // 6):
        out["flags"].append("flicker")
    if longest >= FROZEN_RUN_S:
        out["flags"].append("frozen")
    if out["black_frames"] or float(luma.mean()) < BLACK_LUMA:
        out["flags"].append("black")
    if out["blown_frames"] >= max(2, len(luma) // 10):
        out["flags"].append("blown")
    if jitter >= JITTER_HIGH:
        out["flags"].append("jitter")
    return out


def sharpness(manifest):
    """Laplacian variance per sampled frame (needs cv2); None when unavailable."""
    try:
        import cv2
    except ImportError:
        cv2 = None
    vals = []
    for p in manifest.get("paths") or []:
        if cv2 is None:
            break
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        img = cv2.resize(img, (320, 180), interpolation=cv2.INTER_AREA)
        vals.append(float(cv2.Laplacian(img, cv2.CV_64F).var()))
    if not vals:
        return None
    return {"median": round(float(np.median(vals)), 1), "max": round(float(max(vals)), 1),
            "n": len(vals), "worst_frame": int(np.argmin(vals)), "best_frame": int(np.argmax(vals))}


_aesthetic_models = None


def aesthetic(models_cache, manifest, sharp):
    """LAION improved-aesthetic-predictor over CLIP ViT-L/14; None when not installed."""
    weights = Path(models_cache) / "models" / "aesthetic" / "sac_logos_ava1_l14_linearMSE.pth"
    hf = Path(models_cache) / "models" / "hf"
    if not weights.exists():
        return None
    try:
        import torch
        from PIL import Image
        from transformers import CLIPModel, CLIPProcessor
    except ImportError:
        return None
    paths = manifest.get("paths") or []
    if not paths:
        return None
    best = paths[sharp.get("best_frame", 0)] if sharp else paths[0]
    try:
        # Loaded once per worker process: CLIP-L is ~1.7 GB and every clip uses it.
        global _aesthetic_models
        if _aesthetic_models is None:
            model = CLIPModel.from_pretrained("openai/clip-vit-large-patch14", cache_dir=str(hf))
            proc = CLIPProcessor.from_pretrained("openai/clip-vit-large-patch14", cache_dir=str(hf))
            _aesthetic_models = (model, proc, _load_aesthetic_head(torch, weights))
        model, proc, head = _aesthetic_models
        img = Image.open(best).convert("RGB")
        pixels = proc(images=img, return_tensors="pt")["pixel_values"]
        with torch.no_grad():
            # vision tower + visual projection == CLIP's image embedding. The predictor was
            # trained on the L2-normalised embedding, which is why the raw output is far off
            # scale (measured: 21.4 and -4.2) unless it is normalised here.
            pooled = model.vision_model(pixel_values=pixels).pooler_output
            emb = model.visual_projection(pooled).float()
            emb = emb / emb.norm(p=2, dim=-1, keepdim=True).clamp_min(1e-12)
            score = float(head(emb).item())
        return round(score, 2)
    except Exception as error:  # model weights or torch missing: the flag is simply absent
        if os.environ.get("WANGP_BROWSER_VERBOSE"):
            print(f"[defects] aesthetic skipped: {error}", file=sys.stderr)
        return None


def _load_aesthetic_head(torch, weights):
    """The MLP from christophschuhmann/improved-aesthetic-predictor (MIT), CPU is enough."""

    class MLP(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.layers = torch.nn.Sequential(
                torch.nn.Linear(768, 1024), torch.nn.Dropout(0.2),
                torch.nn.Linear(1024, 128), torch.nn.Dropout(0.2),
                torch.nn.Linear(128, 64), torch.nn.Dropout(0.1),
                torch.nn.Linear(64, 16), torch.nn.Linear(16, 1))

        def forward(self, x):
            return self.layers(x)

    head = MLP()
    head.load_state_dict(torch.load(str(weights), map_location="cpu"))
    head.eval()
    return head


def analyse(ffmpeg, cache_dir, key, path, manifest=None):
    started = time.monotonic()
    manifest = manifest or frames.load(cache_dir, key)
    if not manifest:  # self-sufficient: sample the frames here rather than depend on job order
        frames.sample(ffmpeg, path, cache_dir, key)
        manifest = frames.load(cache_dir, key) or {}
    probe = manifest.get("probe") or {}
    # The luma pass wants the clip's real frame rate (capped in luma_pass), never the
    # 1 fps P3.1 sampling rate: at 1 fps every frame is a cut and everything "flickers".
    fps = probe.get("fps") or manifest.get("source_fps") or MAX_GREY_FPS
    seq, eff = luma_pass(ffmpeg, path, fps)
    res = grey_stats(seq, eff)
    flags = list(res.pop("flags"))
    sharp = sharpness(manifest)
    aes = aesthetic(cache_dir, manifest, sharp) if sharp else None
    if sharp and sharp["median"] < BLUR_LAP:
        flags.append("blur")
    if aes is not None and aes < LOW_AESTHETIC:
        flags.append("low_aesthetic")
    out = {"path": str(path), "key": key, "version": VERSION, "flags": sorted(set(flags)),
           "luma": res, "sharpness": sharp, "aesthetic": aes,
           "frames": {"sampled": len(manifest.get("paths") or []), "grey": int(len(seq))},
           "ms": int((time.monotonic() - started) * 1000)}
    return out


def save(cache_dir, key, result):
    folder = defects_dir(cache_dir)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{key}.json"
    tmp = target.with_name(f"{target.name}.tmp")
    tmp.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    tmp.replace(target)
    return target


def load(cache_dir, key):
    try:
        return json.loads(result_path(cache_dir, key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_job(job, ctx):
    """Worker handler for kind 'defects'."""
    cache = Path(ctx["cache"])
    done = load(cache, job["key"])
    if done and done.get("version") == VERSION:  # C6: same key -> never redone
        return {k: done.get(k) for k in ("flags", "aesthetic", "ms")} | {"cached": True}
    result = analyse(ctx["ffmpeg"], cache, job["key"], job["path"])
    save(cache, job["key"], result)
    return {"flags": result["flags"], "aesthetic": result["aesthetic"], "ms": result["ms"]}
