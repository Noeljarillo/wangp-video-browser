"""Core side of P4.2 auto-tags. Standard library only (C1).

Reads the per-clip results the analysis worker writes to app/.cache/tags/<key>.json
and the vocabulary (app/analysis/tags.yaml is JSON-compatible YAML, so the stdlib
json module parses it). Re-reads only when the folder changes.
"""

import json
import threading
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
TAGS_DIR = APP_DIR / ".cache" / "tags"
VOCAB_PATH = APP_DIR / "analysis" / "tags.yaml"

_lock = threading.Lock()
_memo = {"stamp": None, "by_path": {}}


def vocabulary(path=VOCAB_PATH):
    """[{id, label, labels}] in display order, motion last. Empty when the add-on is absent."""
    try:
        vocab = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    groups = [{"id": g["id"], "label": g["label"], "labels": list(g["labels"])} for g in vocab.get("groups", [])]
    motion = vocab.get("motion")
    if motion:
        groups.append({"id": "motion", "label": motion.get("label", "Camera motion"), "labels": motion["labels"]})
    return groups


def _read_all(folder):
    out = {}
    for file in folder.glob("*.json"):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            out[data["path"]] = data.get("tags") or {}
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return out


def tags_by_path(folder=TAGS_DIR):
    folder = Path(folder)
    try:
        stamp = (str(folder), folder.stat().st_mtime_ns)
    except OSError:
        return {}
    with _lock:
        if _memo["stamp"] != stamp:
            _memo["by_path"], _memo["stamp"] = _read_all(folder), stamp
        return _memo["by_path"]


def payload(entries, folder=TAGS_DIR, vocab_path=VOCAB_PATH):
    """GET /api/tags -> {"groups": [...], "tags": {video id: {group: label}}}."""
    by_path = tags_by_path(folder)
    tags = {e["id"]: by_path[e["path"]] for e in entries if e.get("path") in by_path}
    return {"groups": vocabulary(vocab_path), "tags": tags}
