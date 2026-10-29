"""P3.3 character clustering (worker side, add-on venv: numpy + scikit-learn).

Input: every P3.2 detection embedding in the analysis DB.
  1. Per clip, detections are grouped into *tracks* (agglomerative, cosine, average linkage);
     a track's centroid is the L2-normalised mean embedding. Faces use SFace vectors; people
     use DINOv2 crop vectors, but only in clips without any face (stylised / non-human
     characters), so a real person is not counted twice.
  2. Tracks are first assigned to existing characters (user-authored state in
     app/.data/characters.json): a split/merge override wins, otherwise the nearest exemplar
     whose cosine similarity >= `assign_<modality>` (configurable). This is what makes names,
     merges and splits survive re-analysis and auto-assigns new clips of a named character.
  3. Leftover tracks are clustered across the library (agglomerative, cosine, average
     linkage, `cluster_<modality>` similarity) into new characters.
Derived results go to app/.cache/characters_index.json; the core (characters_api.py) serves them.
"""

import json
import os
import sys
import time
from hashlib import sha1
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis import detstore  # noqa: E402

DEFAULTS = {"assign_face": 0.40, "assign_person": 0.80, "cluster_face": 0.40, "cluster_person": 0.80,
            "track_face": 0.45, "track_person": 0.80}
MAX_EXEMPLARS = 24
MODALITY = {"face": "face", "person": "person"}


def data_path(app_dir):
    return Path(app_dir) / ".data" / "characters.json"


def index_path(cache_dir):
    return Path(cache_dir) / "characters_index.json"


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}")
    tmp.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def empty_data():
    return {"version": 1, "settings": dict(DEFAULTS), "characters": {}, "overrides": {}, "aliases": {}}


def _norm(m):
    import numpy as np
    m = np.asarray(m, dtype="float32")
    if m.ndim == 1:
        return m / (np.linalg.norm(m) or 1.0)
    return m / np.clip(np.linalg.norm(m, axis=1, keepdims=True), 1e-8, None)


def _agglomerate(vectors, min_similarity):
    """Labels for rows of `vectors` (cosine, average linkage)."""
    import numpy as np
    if len(vectors) == 1:
        return np.zeros(1, dtype=int)
    from sklearn.cluster import AgglomerativeClustering
    model = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                    distance_threshold=1.0 - float(min_similarity))
    return model.fit_predict(np.asarray(vectors, dtype="float32"))


def build_tracks(rows, settings):
    """rows: (key, n, frame, kind, score, w, h, model, emb). Returns list of track dicts."""
    import numpy as np
    by_clip = {}
    for key, n, frame, kind, score, w, h, _model, emb in rows:
        by_clip.setdefault(key, {}).setdefault(kind, []).append((n, frame, score * w * h, emb))
    tracks = []
    for key, kinds in by_clip.items():
        for kind in ("face", "person"):
            dets = kinds.get(kind) or []
            if not dets or (kind == "person" and kinds.get("face")):
                continue
            vecs = _norm([d[3] for d in dets])
            labels = _agglomerate(vecs, settings[f"track_{kind}"])
            for label in sorted(set(labels.tolist())):
                idx = [i for i, lab in enumerate(labels.tolist()) if lab == label]
                best = max(idx, key=lambda i: dets[i][2])
                ns = sorted(dets[i][0] for i in idx)
                tracks.append({"id": f"{key}:{kind}:{ns[0]}", "key": key, "modality": kind,
                               "dets": ns, "frames": len({dets[i][1] for i in idx}), "best": dets[best][0],
                               "centroid": _norm(np.mean(vecs[idx], axis=0)).tolist()})
    return tracks


def _resolve(cid, aliases):
    seen = set()
    while cid in aliases and cid not in seen:
        seen.add(cid)
        cid = aliases[cid]
    return cid


def assign(tracks, data):
    """Mutates data (new characters, pruned empties). Returns {track id: character id}."""
    import numpy as np
    settings = dict(DEFAULTS, **data.get("settings", {}))
    chars, aliases, overrides = data["characters"], data.get("aliases", {}), data.get("overrides", {})
    out, leftovers = {}, []
    for track in tracks:
        forced = _resolve(overrides.get(track["id"], ""), aliases)
        if forced in chars:
            out[track["id"]] = forced
            continue
        best, best_sim = None, -1.0
        for cid, char in chars.items():
            if char.get("modality") != track["modality"] or not char.get("exemplars"):
                continue
            sim = float(np.max(_norm(char["exemplars"]) @ np.asarray(track["centroid"], dtype="float32")))
            if sim > best_sim:
                best, best_sim = cid, sim
        if best is not None and best_sim >= settings[f"assign_{track['modality']}"]:
            out[track["id"]] = best
        else:
            leftovers.append(track)
    for modality in ("face", "person"):
        group = [t for t in leftovers if t["modality"] == modality]
        if not group:
            continue
        labels = _agglomerate(_norm([t["centroid"] for t in group]), settings[f"cluster_{modality}"]).tolist()
        for label in sorted(set(labels)):
            members = [t for t, lab in zip(group, labels) if lab == label]
            cid = "c" + sha1(min(t["id"] for t in members).encode()).hexdigest()[:10]
            chars[cid] = {"name": "", "ignored": False, "modality": modality, "created": time.time(),
                          "exemplars": [[round(v, 4) for v in t["centroid"]] for t in members[:MAX_EXEMPLARS]]}
            for t in members:
                out[t["id"]] = cid
    used = set(out.values())
    for cid in [c for c, ch in chars.items() if c not in used and not ch.get("name") and not ch.get("ignored")
                and not ch.get("user")]:
        del chars[cid]
    return out


def build_index(tracks, assignment, data):
    chars = {}
    for t in tracks:
        cid = assignment.get(t["id"])
        if not cid:
            continue
        c = chars.setdefault(cid, {"clips": [], "tracks": 0, "best": None, "score": -1})
        if t["key"] not in c["clips"]:
            c["clips"].append(t["key"])
        c["tracks"] += 1
        if t["frames"] > c["score"]:
            c["score"], c["best"] = t["frames"], {"key": t["key"], "n": t["best"]}
    clips = {}
    for cid, c in chars.items():
        for key in c["clips"]:
            clips.setdefault(key, []).append(cid)
    return {"updated": time.time(), "characters": chars, "clips": clips,
            "tracks": {t["id"]: {"key": t["key"], "cid": assignment.get(t["id"]), "modality": t["modality"],
                                 "best": t["best"], "centroid": [round(v, 4) for v in t["centroid"]]}
                       for t in tracks}}


def recluster(cache_dir, db_path, app_dir):
    started = time.monotonic()
    data = read_json(data_path(app_dir), None) or empty_data()
    data.setdefault("settings", dict(DEFAULTS))
    for name in ("characters", "overrides", "aliases"):
        data.setdefault(name, {})
    conn = detstore.connect(db_path)
    try:
        rows = list(detstore.all_embeddings(conn))
    finally:
        conn.close()
    tracks = build_tracks(rows, dict(DEFAULTS, **data["settings"]))
    assignment = assign(tracks, data)
    index = build_index(tracks, assignment, data)
    write_json(data_path(app_dir), data)
    write_json(index_path(cache_dir), index)
    return {"tracks": len(tracks), "characters": len(index["characters"]),
            "ms": int((time.monotonic() - started) * 1000)}


def run_job(job, ctx):
    """Worker handler for kind 'characters' (library-wide; the key is just a request id)."""
    cache = Path(ctx["cache"])
    return recluster(cache, ctx.get("db") or cache / "analysis.db", ctx.get("app") or cache.parent)


if __name__ == "__main__":
    app = Path(__file__).resolve().parent.parent
    print(recluster(app / ".cache", app / ".cache" / "analysis.db", app))
