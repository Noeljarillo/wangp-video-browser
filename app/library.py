"""
User-authored library data: ratings, keep/reject, tags and collections.

Stored in a sidecar JSON file (`app/.data/library.json`), never in the videos
themselves (C4). Entries are keyed by a content-stable id - sha1 of the first
1 MB plus the file size - so renaming or moving a clip keeps its data. `Reset`
only removes `app/env` and `app/.cache`, so `app/.data` survives it.

Standard library only (C1).
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime
from hashlib import sha1
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / ".data"
LIBRARY_FILE = DATA_DIR / "library.json"

STATUSES = ("keep", "reject")
HEAD_BYTES = 1024 * 1024
MAX_TAG_LEN = 64
MAX_TAGS = 64

_lock = threading.Lock()
_cache = {"path": None, "data": None}


def content_id(path, size=None):
    """sha1(first 1 MB + size) - stable across renames and moves."""
    size = os.path.getsize(path) if size is None else size
    digest = sha1()
    with open(path, "rb") as handle:
        digest.update(handle.read(HEAD_BYTES))
    digest.update(str(size).encode("ascii"))
    return digest.hexdigest()[:20]


def _empty():
    return {"version": 1, "items": {}}


def load(path=None):
    path = Path(path or LIBRARY_FILE)
    with _lock:
        if _cache["path"] == path and _cache["data"] is not None:
            return _cache["data"]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
                data = _empty()
        except (OSError, ValueError):
            data = _empty()
        _cache.update(path=path, data=data)
        return data


def _write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def get(cid, path=None):
    return dict(load(path)["items"].get(cid) or {})


def _clean_list(values):
    out = []
    for value in values if isinstance(values, list) else []:
        text = " ".join(str(value).split())[:MAX_TAG_LEN]
        if text and text not in out:
            out.append(text)
    return out[:MAX_TAGS]


def normalise_patch(patch):
    """Validate a client patch; unknown keys are dropped, bad values raise ValueError."""
    clean = {}
    if not isinstance(patch, dict):
        raise ValueError("patch must be an object")
    if "rating" in patch:
        rating = patch["rating"]
        if rating in (None, 0):
            clean["rating"] = None
        elif isinstance(rating, int) and not isinstance(rating, bool) and 1 <= rating <= 5:
            clean["rating"] = rating
        else:
            raise ValueError("rating must be 0-5")
    if "status" in patch:
        status = patch["status"]
        if status not in STATUSES and status not in (None, ""):
            raise ValueError("status must be keep, reject or empty")
        clean["status"] = status or None
    for key in ("tags", "collections"):
        if key in patch:
            clean[key] = _clean_list(patch[key])
    return clean


def update(cids, patch, path=None):
    """Apply a validated patch to every content id; returns {cid: item}."""
    patch = normalise_patch(patch)
    path = Path(path or LIBRARY_FILE)
    data = load(path)
    result = {}
    with _lock:
        items = data["items"]
        for cid in cids:
            item = dict(items.get(cid) or {})
            item.pop("updated", None)
            for key, value in patch.items():
                if value in (None, []):
                    item.pop(key, None)
                else:
                    item[key] = value
            if item:
                item["updated"] = round(time.time(), 3)
                items[cid] = item
            else:
                items.pop(cid, None)
            result[cid] = dict(item)
        _write_atomic(path, data)
    return result


def forget(cids, path=None):
    path = Path(path or LIBRARY_FILE)
    data = load(path)
    with _lock:
        for cid in cids:
            data["items"].pop(cid, None)
        _write_atomic(path, data)


def reset_cache():
    with _lock:
        _cache.update(path=None, data=None)


# ---------------------------------------------------------------------------
# Move to the OS trash (never `rm`, C4)
# ---------------------------------------------------------------------------

def _xdg_home_trash():
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "Trash"


def _unique_name(files_dir, name):
    stem, suffix = os.path.splitext(name)
    candidate, n = name, 1
    while (files_dir / candidate).exists() or (files_dir.parent / "info" / f"{candidate}.trashinfo").exists():
        n += 1
        candidate = f"{stem}.{n}{suffix}"
    return candidate


def trash_freedesktop(path, trash_dir=None):
    """Freedesktop.org Trash spec: move into Trash/files and write a .trashinfo."""
    path = Path(path).resolve()
    trash = Path(trash_dir) if trash_dir else _xdg_home_trash()
    files_dir, info_dir = trash / "files", trash / "info"
    files_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    info_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    name = _unique_name(files_dir, path.name)
    info = info_dir / f"{name}.trashinfo"
    # O_EXCL reserves the name, as the spec requires.
    fd = os.open(info, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write("[Trash Info]\n")
        handle.write(f"Path={urllib.parse.quote(str(path))}\n")
        handle.write(f"DeletionDate={datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\n")
    try:
        shutil.move(str(path), str(files_dir / name))
    except OSError:
        info.unlink(missing_ok=True)
        raise
    return files_dir / name


def move_to_trash(path, trash_dir=None):
    """Move one file to the OS trash. Raises OSError when no trash is available."""
    path = Path(path)
    if not path.is_file():
        raise OSError(f"not a file: {path}")
    if trash_dir is None and sys.platform.startswith("linux"):
        gio = shutil.which("gio")
        if gio:
            result = subprocess.run([gio, "trash", str(path)], capture_output=True, timeout=60, check=False)
            if result.returncode == 0 and not path.exists():
                return "gio"
        trash_freedesktop(path)
        return "freedesktop"
    if trash_dir is not None:
        trash_freedesktop(path, trash_dir)
        return "freedesktop"
    if sys.platform == "darwin":
        target = Path.home() / ".Trash"
        target.mkdir(exist_ok=True)
        name = _unique_name(target, path.name) if (target / path.name).exists() else path.name
        shutil.move(str(path), str(target / name))
        return "macos"
    raise OSError("moving to the trash is not supported on this system")
