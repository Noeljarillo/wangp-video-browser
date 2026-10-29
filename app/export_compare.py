"""Export comparisons (P6.1).

Renders the current comparison (side-by-side or wipe) to MP4 / WebM / GIF with
burnt-in labels (seed, steps and the settings that differ between the clips),
and a contact-sheet PNG of a take group. Everything goes through ffmpeg; jobs
run one at a time on a single worker thread and write only into
app/.cache/exports/ (user videos are only ever read, C4).
"""

import hashlib
import json
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
EXPORT_DIR = APP_DIR / ".cache" / "exports"
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
FORMATS = ("mp4", "webm", "gif")
MODES = ("side", "wipe")
RENDER_VERSION = 2  # bump when the ffmpeg recipe changes, so cached exports re-render
MIME = {"mp4": "video/mp4", "webm": "video/webm", "gif": "image/gif", "png": "image/png"}

# Settings never worth a label: the prompt is shared by design in a take group,
# and these are bookkeeping, not generation choices.
SKIP_KEYS = {"seed", "num_inference_steps", "prompt", "negative_prompt", "creation_date", "creation_timestamp",
             "generation_time", "settings_version", "model_filename", "_source", "_raw", "workflow"}
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
)


class ExportError(Exception):
    pass


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

def _short(value, limit=22):
    if isinstance(value, float):
        value = round(value, 3)
    if isinstance(value, (dict, list)):
        value = json.dumps(value, separators=(",", ":"))
    text = str(value).replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "~"


def differing_keys(metas, limit=3):
    """Settings (beyond seed/steps) whose values differ across the clips."""
    keys = []
    seen = set()
    for meta in metas:
        for key in meta or {}:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    out = []
    for key in keys:
        if key in SKIP_KEYS or key.startswith("_"):
            continue
        values = [json.dumps((m or {}).get(key), sort_keys=True, default=str) for m in metas]
        if len(set(values)) > 1:
            out.append(key)
        if len(out) >= limit:
            break
    return out


def labels_for(entries):
    """One label line per clip: 'seed 42  ·  8 steps  ·  guidance_scale=5'."""
    metas = [e.get("meta") or {} for e in entries]
    diff = differing_keys(metas)
    labels = []
    for entry, meta in zip(entries, metas):
        parts = []
        if meta.get("seed") is not None:
            parts.append(f"seed {meta['seed']}")
        if meta.get("num_inference_steps") is not None:
            parts.append(f"{meta['num_inference_steps']} steps")
        parts += [f"{k}={_short(meta.get(k))}" for k in diff]
        if not parts:
            parts.append(_short(entry.get("name", ""), 40))
        labels.append("  |  ".join(parts))
    return labels


# ---------------------------------------------------------------------------
# ffmpeg command building (pure, unit-tested)
# ---------------------------------------------------------------------------

def find_font():
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def _esc(path):
    """Escape a path for use as a filter option value."""
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _drawtext(textfile, font, align="left", size="max(14\\,h/36)"):
    x = "12" if align == "left" else "w-tw-12"
    opts = [f"textfile='{_esc(textfile)}'", "expansion=none", f"fontsize={size}", "fontcolor=white",
            "box=1", "boxcolor=black@0.6", "boxborderw=6", f"x={x}", "y=12"]
    if font:
        opts.insert(0, f"fontfile='{_esc(font)}'")
    return "drawtext=" + ":".join(opts)


def _even(n):
    n = int(n)
    return n - (n % 2)


def build_video_command(ffmpeg, entries, label_files, out, mode="side", fmt="mp4", wipe=50, font=None,
                        height=480, fps=24, encoders=None):
    """ffmpeg argv for a side-by-side or wipe export."""
    if mode == "wipe":
        entries, label_files = entries[:2], label_files[:2]
    durations = [((e.get("probe") or {}).get("duration") or 0) for e in entries]
    known = [d for d in durations if d > 0]
    duration = min(known) if known else 10
    duration = min(duration, 60)
    if fmt == "gif":
        # GIF has no inter-frame compression worth the name: keep it small.
        height = min(height, 240)
        fps = min(fps, 10)
        duration = min(duration, 8)
    probe = entries[0].get("probe") or {}
    src_w, src_h = probe.get("width") or 16, probe.get("height") or 9
    h = _even(min(height, src_h) or height)
    w = _even(h * src_w / src_h)

    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for entry in entries:
        cmd += ["-t", f"{duration:.3f}", "-i", entry["path"]]
    parts = []
    n = len(entries)
    if mode == "side":
        for i, tf in enumerate(label_files):
            parts.append(f"[{i}:v]scale=-2:{h},setsar=1,fps={fps},{_drawtext(tf, font)}[v{i}]")
        parts.append("".join(f"[v{i}]" for i in range(n)) + f"hstack=inputs={n}:shortest=1[out]")
    else:
        split = max(0.0, min(1.0, float(wipe) / 100.0))
        cut = _even(w * split)
        parts.append(f"[0:v]scale={w}:{h},setsar=1,fps={fps},{_drawtext(label_files[0], font)}[a]")
        parts.append(f"[1:v]scale={w}:{h},setsar=1,fps={fps},{_drawtext(label_files[1], font, 'right')},"
                     f"crop={max(2, w - cut)}:{h}:{cut}:0[b]")
        parts.append(f"[a][b]overlay={cut}:0:shortest=1,drawbox=x={max(0, cut - 1)}:y=0:w=2:h={h}:color=white@0.9:t=fill[out]")
    if fmt == "gif":
        parts[-1] = parts[-1][: -len("[out]")] + ",split[g1][g2];[g1]palettegen=stats_mode=diff[p];[g2][p]paletteuse=dither=bayer[out]"
    cmd += ["-filter_complex", ";".join(parts), "-map", "[out]", "-an"]
    encoders = encoders or set()
    if fmt == "mp4":
        if "libx264" in encoders or not encoders:
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        else:
            cmd += ["-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p"]
    elif fmt == "webm":
        if "libvpx-vp9" in encoders or not encoders:
            cmd += ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-deadline", "realtime", "-cpu-used", "8",
                    "-row-mt", "1", "-pix_fmt", "yuv420p"]
        else:
            cmd += ["-c:v", "libvpx", "-crf", "10", "-b:v", "2M", "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-loop", "0"]
    cmd.append(str(out))
    return cmd


def build_sheet_command(ffmpeg, entries, label_files, out, font=None, cell_w=360):
    """ffmpeg argv for a contact sheet: one labelled frame per clip, tiled."""
    n = len(entries)
    cols = min(4, n) if n > 1 else 1
    rows = (n + cols - 1) // cols
    probe = entries[0].get("probe") or {}
    src_w, src_h = probe.get("width") or 16, probe.get("height") or 9
    cell_h = _even(cell_w * src_h / src_w)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for entry in entries:
        duration = (entry.get("probe") or {}).get("duration") or 0
        seek = max(0.0, min(duration * 0.5, 30.0)) if duration else 0.0
        cmd += ["-ss", f"{seek:.3f}", "-i", entry["path"]]
    parts = []
    for i, tf in enumerate(label_files):
        parts.append(f"[{i}:v]trim=end_frame=1,scale={cell_w}:{cell_h}:force_original_aspect_ratio=decrease,"
                     f"pad={cell_w}:{cell_h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=rgb24,"
                     + _drawtext(tf, font, size="13") + f"[c{i}]")
    parts.append("".join(f"[c{i}]" for i in range(n)) +
                 f"concat=n={n}:v=1:a=0,tile={cols}x{rows}:padding=4:margin=4:color=0x14161d[out]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[out]", "-frames:v", "1", "-update", "1", str(out)]
    return cmd


# ---------------------------------------------------------------------------
# Jobs: one worker thread, one ffmpeg at a time
# ---------------------------------------------------------------------------

_jobs = {}
_jobs_lock = threading.Lock()
_queue = queue.Queue()
_worker = None
_encoders_cache = {}


def _encoders(ffmpeg):
    if ffmpeg not in _encoders_cache:
        try:
            text = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True,
                                  timeout=20, check=False).stdout
            _encoders_cache[ffmpeg] = {line.split()[1] for line in text.splitlines()
                                       if len(line.split()) > 1 and line.startswith(" V")}
        except (OSError, subprocess.SubprocessError):
            _encoders_cache[ffmpeg] = set()
    return _encoders_cache[ffmpeg]


def _key(kind, entries, opts):
    parts = [kind, str(RENDER_VERSION), json.dumps(opts, sort_keys=True)] + [f"{e['path']}|{e.get('size')}|{e.get('mtime')}" for e in entries]
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def public_job(job):
    return {k: v for k, v in job.items() if not k.startswith("_")}


def submit(ffmpeg, entries, kind="video", mode="side", fmt="mp4", wipe=50):
    """Queue an export. Returns the job dict (already 'done' if cached)."""
    if not ffmpeg:
        raise ExportError("ffmpeg was not found. Install ffmpeg (or WanGP's bundled ffmpeg_bins) to export comparisons.")
    if kind == "sheet":
        if not entries:
            raise ExportError("pick at least one clip for a contact sheet")
        entries = entries[:16]
        opts, ext = {}, "png"
    else:
        if mode not in MODES:
            raise ExportError(f"mode must be one of {', '.join(MODES)}")
        if fmt not in FORMATS:
            raise ExportError(f"format must be one of {', '.join(FORMATS)}")
        if len(entries) < 2:
            raise ExportError("pick at least two clips to export a comparison")
        if mode == "wipe" and len(entries) != 2:
            raise ExportError("wipe needs exactly two clips")
        entries = entries[:4]
        wipe = max(0, min(100, int(float(wipe))))
        opts, ext = {"mode": mode, "fmt": fmt, "wipe": wipe if mode == "wipe" else None}, fmt
    job_id = _key(kind, entries, opts)
    name = f"{'sheet' if kind == 'sheet' else 'compare-' + mode}-{job_id}.{ext}"
    out = EXPORT_DIR / name
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job and job["status"] in ("queued", "running"):
            return public_job(job)
        job = {"id": job_id, "name": name, "kind": kind, "status": "queued", "error": None,
               "url": f"/exports/{name}", "mime": MIME[ext], "_entries": entries, "_opts": opts, "_ffmpeg": ffmpeg}
        if out.is_file() and out.stat().st_size > 0:
            job["status"] = "done"
            job["size"] = out.stat().st_size
        _jobs[job_id] = job
        if job["status"] == "queued":
            _queue.put(job_id)
            _ensure_worker()
        return public_job(job)


def get_job(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
        return public_job(job) if job else None


def export_path(name):
    """Resolve a download name to a file inside EXPORT_DIR, or None."""
    if not NAME_RE.match(name or "") or name.startswith("."):
        return None
    path = EXPORT_DIR / name
    return path if path.is_file() else None


def _ensure_worker():
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_run, name="export-compare", daemon=True)
        _worker.start()


def _run():
    while True:
        job_id = _queue.get()
        with _jobs_lock:
            job = _jobs.get(job_id)
            if not job:
                continue
            job["status"] = "running"
            job["started"] = time.time()
        try:
            _render(job)
            with _jobs_lock:
                job["status"] = "done"
                job["size"] = (EXPORT_DIR / job["name"]).stat().st_size
        except (ExportError, OSError, subprocess.SubprocessError) as error:
            with _jobs_lock:
                job["status"] = "error"
                job["error"] = str(error)[-600:]
        finally:
            with _jobs_lock:
                job["finished"] = time.time()


def _render(job):
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    entries, opts, ffmpeg = job["_entries"], job["_opts"], job["_ffmpeg"]
    out = EXPORT_DIR / job["name"]
    tmp = out.with_name(f"tmp-{job['name']}")
    label_files = []
    for i, text in enumerate(labels_for(entries)):
        path = EXPORT_DIR / f"label-{job['id']}-{i}.txt"
        path.write_text(text, encoding="utf-8")
        label_files.append(path)
    font = find_font()
    try:
        if job["kind"] == "sheet":
            cmd = build_sheet_command(ffmpeg, entries, label_files, tmp, font=font)
        else:
            cmd = build_video_command(ffmpeg, entries, label_files, tmp, mode=opts["mode"], fmt=opts["fmt"],
                                      wipe=opts.get("wipe") or 50, font=font, encoders=_encoders(ffmpeg))
        result = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=900, check=False)
        if result.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
            raise ExportError((result.stderr or "ffmpeg failed").strip().splitlines()[-1] if result.stderr else "ffmpeg failed")
        os.replace(tmp, out)
    finally:
        for path in label_files:
            try:
                path.unlink()
            except OSError:
                pass
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
