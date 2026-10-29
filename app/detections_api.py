"""Core-side read API for P3.2 detections (standard library only, C1/C2).

GET /api/analysis/detections/<id> -> boxes (normalised 0..1) per sampled frame,
read from app/.cache/analysis.db. Works (and reports state) when the add-on is absent.
"""

import json
import os
from pathlib import Path

import analysis_host

FACES_DIR = analysis_host.CACHE_DIR / "faces"
FRAMES_DIR = analysis_host.CACHE_DIR / "frames"


def clip_key(entry):
    from analysis import jobqueue
    try:
        mtime_ns = os.stat(entry["path"]).st_mtime_ns
    except OSError:
        return None
    return jobqueue.cache_key(entry["path"], entry["size"], mtime_ns)


def _frame_times(key):
    try:
        manifest = json.loads((FRAMES_DIR / key / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return manifest.get("times") or []


def detections(entry, db_path=None):
    if not analysis_host.installed():
        return {"id": entry["id"], "installed": False, "state": "absent", "detections": []}
    key = clip_key(entry)
    db_path = db_path or analysis_host.DB_PATH
    if not key or not Path(db_path).is_file():
        return {"id": entry["id"], "installed": True, "state": "pending", "detections": []}
    from analysis import detstore
    conn = detstore.connect(db_path)
    try:
        run = detstore.run_info(conn, key)
        rows = detstore.load(conn, key) if run else []
    finally:
        conn.close()
    for row in rows:
        row["crop"] = f"/api/analysis/crop/{entry['id']}/{row['n']}"
    return {"id": entry["id"], "installed": True, "state": "done" if run else "pending", "key": key,
            "run": run, "times": _frame_times(key), "detections": rows}


def crop_path(entry, n_text):
    """Allow-list: only <cache>/faces/<this clip's key>/<int>.jpg."""
    if not entry or not str(n_text).isdigit():
        return None
    key = clip_key(entry)
    target = FACES_DIR / str(key) / f"{int(n_text)}.jpg"
    return target if key and target.is_file() else None
