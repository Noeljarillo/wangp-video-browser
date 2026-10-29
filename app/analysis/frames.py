"""P3.1 frame sampling: N frames per clip into app/.cache/frames/<cache key>/.

Default 1 fps, at most 32 frames; clips longer than 32 s are sampled evenly
across their whole length instead of only the first 32 s. Frames are JPEGs
capped at 1024 px on the long side, plus a manifest.json. Every later analyser
(faces, embeddings, tags) reads these instead of decoding the video again.
The source video is only read (C4). Standard library + ffmpeg only.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

DEFAULT_FPS = 1.0
MAX_FRAMES = 32
LONG_SIDE = 1024
SCALE = (f"scale='if(gt(iw,ih),min({LONG_SIDE},iw),-2)':'if(gt(iw,ih),-2,min({LONG_SIDE},ih))'")


def frames_dir(cache_dir, key):
    return Path(cache_dir) / "frames" / key


def load(cache_dir, key):
    """Manifest of an already-sampled clip, with absolute frame paths, or None."""
    folder = frames_dir(cache_dir, key)
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    manifest["paths"] = [str(folder / name) for name in manifest.get("files", [])]
    return manifest


def sample_rate(duration, fps=DEFAULT_FPS, max_frames=MAX_FRAMES):
    if duration and duration * fps > max_frames:
        return max_frames / float(duration)
    return fps


def sample(ffmpeg, path, cache_dir, key, duration=None, fps=DEFAULT_FPS, max_frames=MAX_FRAMES):
    existing = load(cache_dir, key)
    if existing:  # C6: same path+size+mtime -> same key -> never redone
        return dict({k: v for k, v in existing.items() if k != "paths"}, cached=True)
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")
    final = frames_dir(cache_dir, key)
    tmp = final.with_name(f"{key}.tmp{os.getpid()}")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    rate = sample_rate(duration, fps, max_frames)
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-i", str(path),
               "-vf", f"fps={rate:.6f},{SCALE}", "-frames:v", str(max_frames), "-q:v", "3",
               str(tmp / "f%03d.jpg")]
    try:
        res = subprocess.run(command, capture_output=True, text=True, errors="ignore", timeout=300, check=False)
        files = sorted(p.name for p in tmp.glob("f*.jpg") if p.stat().st_size > 0)
        if not files:
            raise RuntimeError((res.stderr or "ffmpeg produced no frames").strip()[-300:])
        manifest = {"fps": round(rate, 6), "count": len(files), "files": files, "duration": duration,
                    "times": [round(i / rate, 3) for i in range(len(files))],
                    "bytes": sum((tmp / f).stat().st_size for f in files)}
        (tmp / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        shutil.rmtree(final, ignore_errors=True)
        os.replace(tmp, final)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return manifest


def run_job(job, ctx):
    """Worker handler for kind 'frames'."""
    payload = job.get("payload") or {}
    m = sample(ctx.get("ffmpeg"), job["path"], ctx["cache"], job["key"], duration=payload.get("duration"))
    return {"count": m["count"], "bytes": m["bytes"], "fps": m["fps"], "cached": bool(m.get("cached"))}
