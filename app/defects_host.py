"""Core side of P5.1 defect flags. Standard library only (C1).

Reads the per-clip results the analysis worker writes to app/.cache/defects/<key>.json.
Re-reads only when the folder changes, the same way tags_host does.
"""

import json
import threading
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DEFECTS_DIR = APP_DIR / ".cache" / "defects"

# Display order and wording for the badges and facets.
FLAGS = [
    ("flicker", "Flicker", "luma spikes"),
    ("frozen", "Frozen", "stuck frames"),
    ("black", "Black", "black frames"),
    ("blown", "Blown", "blown highlights"),
    ("jitter", "Jitter", "temporal jitter"),
    ("blur", "Soft", "low sharpness"),
    ("low_aesthetic", "Low score", "aesthetic below 4"),
]
FLAG_LABEL = {key: label for key, label, _ in FLAGS}

_lock = threading.Lock()
_memo = {"stamp": None, "by_path": {}}


def _read_all(folder):
    out = {}
    for file in Path(folder).glob("*.json"):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            out[data["path"]] = {
                "flags": list(data.get("flags") or []),
                "aesthetic": data.get("aesthetic"),
                "jitter": (data.get("luma") or {}).get("jitter"),
                "sharpness": (data.get("sharpness") or {}).get("median"),
                "frozen_s": (data.get("luma") or {}).get("frozen_longest_s"),
            }
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def by_path(folder=DEFECTS_DIR):
    folder = Path(folder)
    try:
        stamp = (str(folder), folder.stat().st_mtime_ns)
    except OSError:
        return {}
    with _lock:
        if _memo["stamp"] != stamp:
            _memo["by_path"], _memo["stamp"] = _read_all(folder), stamp
        return _memo["by_path"]


def payload(entries, folder=DEFECTS_DIR):
    """GET /api/defects -> {"flags": [...], "clips": {id: {...}}}."""
    results = by_path(folder)
    clips = {}
    for entry in entries:
        hit = results.get(entry.get("path"))
        if hit:
            clips[entry["id"]] = hit
    return {"flags": [{"key": k, "label": label, "hint": hint} for k, label, hint in FLAGS],
            "clips": clips}
