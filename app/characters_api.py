"""Core side of P3.3 characters (standard library only, C1).

Reads app/.cache/characters_index.json (derived, written by the worker's clusterer) and
app/.data/characters.json (user-authored: names, ignore, merges, splits, thresholds; Reset
keeps it, C4). User actions are applied to both files immediately so the UI updates
without waiting for a re-cluster; the clusterer honours the same data on its next run.
"""

import json
import os
import threading
import time
from hashlib import sha1
from pathlib import Path

import analysis_host

APP_DIR = analysis_host.APP_DIR
DATA_PATH = APP_DIR / ".data" / "characters.json"
INDEX_PATH = analysis_host.CACHE_DIR / "characters_index.json"
FACES_DIR = analysis_host.CACHE_DIR / "faces"
MAX_EXEMPLARS = 24
SETTINGS = ("assign_face", "assign_person", "cluster_face", "cluster_person")

_lock = threading.Lock()
_keys = {}  # (path, size, mtime_ns) -> cache key


def _read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}")
    tmp.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def _data():
    data = _read(DATA_PATH, None) or {"version": 1, "settings": {}, "characters": {}}
    for name in ("settings", "characters", "overrides", "aliases"):
        data.setdefault(name, {})
    return data


def _key(entry):
    from analysis import jobqueue
    try:
        mtime_ns = os.stat(entry["path"]).st_mtime_ns
    except OSError:
        return None
    sig = (entry["path"], entry["size"], mtime_ns)
    if sig not in _keys:
        _keys[sig] = jobqueue.cache_key(*sig)
    return _keys[sig]


def listing(entries):
    """Characters + per-video ids for the UI. entries: the library index."""
    index, data = _read(INDEX_PATH, {}), _data()
    by_key = {}
    for entry in entries:
        key = _key(entry)
        if key:
            by_key[key] = entry["id"]
    out = []
    for cid, info in (index.get("characters") or {}).items():
        meta = data["characters"].get(cid, {})
        ids = [by_key[k] for k in info.get("clips", []) if k in by_key]
        if not ids:
            continue
        out.append({"id": cid, "name": meta.get("name") or "", "ignored": bool(meta.get("ignored")),
                    "modality": meta.get("modality") or "face", "clips": ids, "count": len(ids),
                    "avatar": f"/api/characters/avatar/{cid}"})
    out.sort(key=lambda c: (c["ignored"], not c["name"], -c["count"], c["name"].lower(), c["id"]))
    return {"installed": analysis_host.installed(), "updated": index.get("updated"),
            "settings": data["settings"], "characters": out}


def avatar_path(cid):
    info = (_read(INDEX_PATH, {}).get("characters") or {}).get(cid) or {}
    best = info.get("best") or {}
    key, n = str(best.get("key", "")), best.get("n")
    if not key.isalnum() or not isinstance(n, int):
        return None
    target = FACES_DIR / key / f"{n}.jpg"
    return target if target.is_file() else None


def _tracks_of(index, cid, keys=None):
    return [tid for tid, t in (index.get("tracks") or {}).items()
            if t.get("cid") == cid and (keys is None or t.get("key") in keys)]


def _reindex(index):
    chars = {}
    for tid, t in (index.get("tracks") or {}).items():
        cid = t.get("cid")
        if not cid:
            continue
        c = chars.setdefault(cid, {"clips": [], "tracks": 0, "best": None, "score": -1})
        if t["key"] not in c["clips"]:
            c["clips"].append(t["key"])
        c["tracks"] += 1
        old = (index.get("characters") or {}).get(cid) or {}
        c["best"] = old.get("best") if old.get("best") and old["best"].get("key") in c["clips"] else (
            c["best"] or {"key": t["key"], "n": t.get("best")})
    clips = {}
    for cid, c in chars.items():
        for key in c["clips"]:
            clips.setdefault(key, []).append(cid)
    index["characters"], index["clips"], index["updated"] = chars, clips, time.time()
    return index


def action(payload, entries):
    """rename / ignore / merge / split / settings. Raises ValueError on bad input."""
    op = payload.get("op")
    with _lock:
        data, index = _data(), _read(INDEX_PATH, {})
        chars = data["characters"]
        if op == "settings":
            for name in SETTINGS:
                if name in payload:
                    value = float(payload[name])
                    if not 0.0 < value < 1.0:
                        raise ValueError(f"{name} must be between 0 and 1")
                    data["settings"][name] = value
            _write(DATA_PATH, data)
            return {"settings": data["settings"]}
        cid = str(payload.get("id") or "")
        if cid not in chars:
            raise ValueError("unknown character")
        if op == "rename":
            chars[cid]["name"] = str(payload.get("name") or "").strip()[:80]
            chars[cid]["user"] = True
        elif op == "ignore":
            chars[cid]["ignored"] = bool(payload.get("ignored", True))
            chars[cid]["user"] = True
        elif op == "merge":
            others = [str(o) for o in payload.get("others") or [] if str(o) in chars and str(o) != cid]
            if not others:
                raise ValueError("nothing to merge")
            for other in others:
                if chars[other].get("modality") != chars[cid].get("modality"):
                    raise ValueError("cannot merge a face character with a figure character")
            for other in others:
                chars[cid]["exemplars"] = (chars[cid].get("exemplars", []) + chars[other].get("exemplars", []))[:MAX_EXEMPLARS]
                if not chars[cid].get("name") and chars[other].get("name"):
                    chars[cid]["name"] = chars[other]["name"]
                data["aliases"][other] = cid
                for tid in _tracks_of(index, other):
                    index["tracks"][tid]["cid"] = cid
                del chars[other]
            chars[cid]["user"] = True
        elif op == "split":
            wanted = set(str(i) for i in payload.get("clips") or [])
            keys = {_key(e) for e in entries if e["id"] in wanted}
            moved = _tracks_of(index, cid, keys)
            if not moved or len(moved) == len(_tracks_of(index, cid)):
                raise ValueError("pick some, not all, of this character's clips to split off")
            new = "c" + sha1(f"{cid}:{sorted(moved)[0]}:{time.time()}".encode()).hexdigest()[:10]
            chars[new] = {"name": str(payload.get("name") or "").strip()[:80], "ignored": False, "user": True,
                          "modality": chars[cid].get("modality", "face"), "created": time.time(),
                          "exemplars": [index["tracks"][t]["centroid"] for t in moved][:MAX_EXEMPLARS]}
            moved_set = {tuple(index["tracks"][t]["centroid"]) for t in moved}
            chars[cid]["exemplars"] = [e for e in chars[cid].get("exemplars", []) if tuple(e) not in moved_set]
            if not chars[cid]["exemplars"]:
                chars[cid]["exemplars"] = [index["tracks"][t]["centroid"] for t in _tracks_of(index, cid)
                                           if t not in moved][:MAX_EXEMPLARS]
            chars[cid]["user"] = True
            for tid in moved:
                data["overrides"][tid] = new
                index["tracks"][tid]["cid"] = new
            cid = new
        else:
            raise ValueError("unknown op")
        _write(DATA_PATH, data)
        if index:
            _write(INDEX_PATH, _reindex(index))
    return {"id": cid}


def recluster():
    """Ask the worker for a fresh clustering pass (library-wide job)."""
    if not analysis_host.installed():
        return {"queued": 0}
    from analysis import jobqueue
    conn = jobqueue.connect(analysis_host.DB_PATH)
    try:
        added = jobqueue.enqueue(conn, "characters", [{"path": "library", "size": 0, "mtime_ns": time.time_ns()}])
    finally:
        conn.close()
    analysis_host.start()
    return {"queued": added}
