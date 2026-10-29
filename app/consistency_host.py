"""Core side of P3.4/P3.5 (reference consistency score, identity drift). stdlib only (C1).

Reads the per-clip results the analysis worker writes to app/.cache/consistency/<key>.json.
"""

import json
import threading
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
RESULTS_DIR = APP_DIR / ".cache" / "consistency"

# Buckets the UI filters on; the thresholds match COS_FLOOR/COS_CEIL in analysis/consistency.py
BANDS = [(70, "High"), (40, "Mixed"), (0, "Low")]

_lock = threading.Lock()
_memo = {"stamp": None, "by_path": {}}


def _band(score):
    if score is None:
        return None
    for floor, label in BANDS:
        if score >= floor:
            return label
    return None


def _read_all(folder):
    out = {}
    for file in Path(folder).glob("*.json"):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            drift = data.get("drift") or {}
            out[data["path"]] = {
                "score": data.get("score"),
                "band": _band(data.get("score")),
                "drift": bool(drift.get("flagged")),
                "drift_drop": drift.get("drop"),
                "worst_frame": drift.get("worst_frame"),
                "frames": data.get("frames") or [],
                "drift_frames": drift.get("frames") or [],
                "refs": [{"name": ref.get("name"), "score": ref.get("score")}
                         for ref in (data.get("refs") or [])],
                "note": data.get("note"),
            }
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def by_path(folder=RESULTS_DIR):
    folder = Path(folder)
    try:
        stamp = (str(folder), folder.stat().st_mtime_ns)
    except OSError:
        return {}
    with _lock:
        if _memo["stamp"] != stamp:
            _memo["by_path"], _memo["stamp"] = _read_all(folder), stamp
        return _memo["by_path"]


def payload(entries, folder=RESULTS_DIR):
    """GET /api/consistency -> {"bands": [...], "clips": {id: {...}}}."""
    results = by_path(folder)
    clips = {}
    for entry in entries:
        hit = results.get(entry.get("path"))
        if hit:
            clips[entry["id"]] = hit
    return {"bands": [{"key": label, "label": label, "from": floor} for floor, label in BANDS],
            "clips": clips}
