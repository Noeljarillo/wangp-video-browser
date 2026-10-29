"""Core side of P4.3 captions (opt-in). Standard library only (C1).

Reads app/.cache/captions/<key>.json and the settings in app/.data/captions.json, so the
UI can show whether the feature is on and what it produced. Turning it on is the user's
call: it needs a vision model already loaded in their local LLM server.
"""

import json
import threading
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
RESULTS_DIR = APP_DIR / ".cache" / "captions"
SETTINGS_PATH = APP_DIR / ".data" / "captions.json"

_lock = threading.Lock()
_memo = {"stamp": None, "by_path": {}}


def settings(path=SETTINGS_PATH):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"enabled": False, "reason": "set a local vision model in app/.data/captions.json"}
    return {"enabled": bool(data.get("model")), "endpoint": data.get("endpoint"),
            "model": data.get("model"), "frames": data.get("frames")}


def _read_all(folder):
    out = {}
    for file in Path(folder).glob("*.json"):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            out[data["path"]] = {"captions": data.get("captions") or [],
                                 "adherence": data.get("adherence"), "model": data.get("model")}
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


def payload(entries, folder=RESULTS_DIR, settings_path=SETTINGS_PATH):
    """GET /api/captions -> {"settings": {...}, "clips": {id: {...}}}."""
    results = by_path(folder)
    clips = {}
    for entry in entries:
        hit = results.get(entry.get("path"))
        if hit:
            clips[entry["id"]] = hit
    return {"settings": settings(settings_path), "clips": clips}
