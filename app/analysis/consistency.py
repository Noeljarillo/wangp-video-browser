"""P3.4 reference consistency score and P3.5 identity drift.

Both compare a clip's detected people with something:
  * P3.4 compares them with the reference images the clip was generated from (P1.3), so
    the score answers "does this clip actually look like the reference?".
  * P3.5 compares the clip's frames with each other, so the score answers "does the
    character stay the same person from the first frame to the last?".

Embeddings are DINOv2-small CLS vectors of person crops (faces.py) - one per detection,
already cached in the detection store, so this pass costs no GPU decode of the video.

Per clip result in app/.cache/consistency/<key>.json:
    {"path", "score": 0..100|null, "frames": [{"frame", "t", "score"}],
     "refs": [{"name", "path", "score"}], "drift": {"score", "frames": [...], "flagged": bool},
     "ms", "version"}

Cosine -> 0..100 mapping (calibrated on the 32-clip library, see docs/CONSISTENCY.md):
0.2 -> 0 and 0.8 -> 100, clamped. A different person sits around 0.1-0.3, the same person
with a new pose or lighting around 0.6-0.9, so the mid-band is the informative part.
"""

import json
import time
from pathlib import Path

import numpy as np

from analysis import detstore, faces

VERSION = 2
COS_FLOOR = 0.2          # cosine that scores 0
COS_CEIL = 0.8           # cosine that scores 100
FRAME_PERCENTILE = 75    # a clip is judged on its better three-quarters of frames: a few
                         # occluded or turned-away frames should not sink an otherwise good clip
# The library is 10 s multi-shot clips, so a shot change drops the crop similarity a lot even
# when the character is the same person. Measured over 33 clips the drop runs 0.0 .. 0.81 with
# the top decile above 0.63, so the flag marks the worst tenth rather than every scene change.
DRIFT_DROP = 0.63
DRIFT_ANCHOR_FRAMES = 3  # the identity the clip establishes, from its first frames


def score_from_cosine(cos):
    """Map a cosine similarity to 0..100 with the calibrated band above."""
    value = (float(cos) - COS_FLOOR) / (COS_CEIL - COS_FLOOR)
    return round(max(0.0, min(1.0, value)) * 100.0, 1)


def _unit(vec):
    vec = np.asarray(vec, dtype="float32")
    norm = float(np.linalg.norm(vec)) or 1.0
    return vec / norm


def _stack(vectors):
    return np.stack([_unit(v) for v in vectors]) if vectors else np.zeros((0, 0), dtype="float32")


def pick_kind(rows):
    """Person crops (DINOv2, 384-d) are the main signal; faces (SFace, 128-d) are the fallback.

    The two embedders produce different vector widths, so one pass must never mix them.
    """
    kinds = {row.get("kind") for row in rows if row.get("emb") is not None}
    if "person" in kinds:
        return "person"
    return "face" if "face" in kinds else None


def _rows_by_frame(rows, kind=None):
    """Detections with an embedding, grouped by frame, best box first."""
    kind = kind or pick_kind(rows)
    out = {}
    for row in rows:
        if row.get("emb") is None or (kind and row.get("kind") != kind):
            continue
        out.setdefault(row["frame"], []).append(row)
    for frame in out:
        out[frame].sort(key=lambda r: -(r.get("score") or 0))
    return out


def ref_vectors(models, refs):
    """One embedding per existing reference image, from its person crop when there is one."""
    out = []
    for ref in refs:
        path = ref.get("path")
        if not path or not Path(path).exists():
            continue
        image = models.cv2.imread(str(path))
        if image is None:
            continue
        crop = image
        persons = models.persons([image])
        if persons and persons[0]:
            box = max(persons[0], key=lambda p: max(p["box"][2], p["box"][3]))
            crop = faces._crop(image, box["box"])
        if crop is None:
            continue
        vector = models.embed_crops([crop])       # same embedder as the person crops
        if vector:
            out.append({"name": ref.get("name") or Path(path).name, "path": str(path),
                        "emb": vector[0]})
    return out


def consistency(rows, refs):
    """Per-frame best match against any reference, and the clip score from its top frames."""
    by_frame = _rows_by_frame(rows)
    refs = [ref for ref in refs if ref.get("emb") is not None]
    if not by_frame or not refs:
        return None, []
    ref_matrix = _stack([r["emb"] for r in refs])
    frames = []
    per_ref = [[] for _ in refs]
    for frame in sorted(by_frame):
        cand = _stack([r["emb"] for r in by_frame[frame]])
        sims = cand @ ref_matrix.T                      # (detections, refs)
        best = float(sims.max())
        for index in range(len(refs)):
            per_ref[index].append(float(sims[:, index].max()))
        frames.append({"frame": frame, "t": by_frame[frame][0].get("t"), "score": score_from_cosine(best),
                       "cos": round(best, 4)})
    cosines = [f["cos"] for f in frames]
    score = score_from_cosine(float(np.percentile(cosines, FRAME_PERCENTILE))) if cosines else None
    refs_out = [{"name": ref["name"], "path": ref["path"],
                 "score": score_from_cosine(float(np.max(values))) if values else None}
                for ref, values in zip(refs, per_ref)]
    return ({"score": score, "frames": frames, "refs": refs_out}, frames)


def drift(rows):
    """Identity drift inside the clip: each frame's dominant person against the clip median."""
    by_frame = _rows_by_frame(rows)
    if len(by_frame) < 3:
        return {"score": None, "frames": [], "flagged": False, "note": "too few frames with people"}
    frames = sorted(by_frame)
    # The opening frames are the identity the clip promises; every later frame is measured
    # against them by its BEST match, not by its biggest person: in a two-person scene the
    # largest box changes hands every few frames, which is not drift. A median anchor hides
    # a 50/50 identity flip, which is exactly what this check exists to catch.
    opening = _stack([by_frame[f][0]["emb"] for f in frames[:DRIFT_ANCHOR_FRAMES]])
    anchor = _unit(opening.mean(axis=0))
    sims = np.array([float(max(row["emb"] @ anchor for row in by_frame[f])) for f in frames])
    worst = float(sims.min())
    worst_at = int(frames[int(sims.argmin())])
    first = float(np.mean(sims[:DRIFT_ANCHOR_FRAMES]))
    drop = first - worst
    flagged = drop >= DRIFT_DROP
    return {"score": round(max(0.0, first) * 100, 1),
            "min_cos": round(worst, 4), "drop": round(drop, 4),
            "worst_frame": worst_at,
            "frames": [{"frame": f, "t": by_frame[f][0].get("t"), "cos": round(float(s), 4)}
                       for f, s in zip(frames, sims)],
            "flagged": flagged, "anchor": f"first {DRIFT_ANCHOR_FRAMES} frames"}


def analyse(models, conn, key, payload):
    started = time.monotonic()
    rows = detstore.load(conn, key, embeddings=True)
    refs = ref_vectors(models, payload.get("refs") or []) if payload.get("refs") else []
    cons, _ = consistency(rows, refs)
    result = {"path": payload.get("path"), "version": VERSION,
              "score": (cons or {}).get("score"), "frames": (cons or {}).get("frames") or [],
              "refs": (cons or {}).get("refs") or [], "drift": drift(rows),
              "people": sum(1 for r in rows if r.get("kind") == "person"),
              "ms": int((time.monotonic() - started) * 1000)}
    if cons is None:
        result["note"] = ("no reference images recorded for this clip" if not refs
                          else "no person detected in this clip")
    return result


def save(cache_dir, key, result):
    folder = Path(cache_dir) / "consistency"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{key}.json"
    tmp = target.with_name(f"{target.name}.tmp")
    tmp.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    tmp.replace(target)


def load(cache_dir, key):
    try:
        return json.loads((Path(cache_dir) / "consistency" / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


_models = None


def run_job(job, ctx):
    """Worker handler for kind 'consistency'. Runs the 'faces' pass first if it is missing."""
    global _models
    cache = Path(ctx["cache"])
    done = load(cache, job["key"])
    if done and done.get("version") == VERSION:
        return {"score": done.get("score"), "drift": (done.get("drift") or {}).get("flagged"),
                "cached": True}
    conn = detstore.connect(ctx.get("db") or cache / "analysis.db")
    try:
        if not detstore.run_info(conn, job["key"]):
            faces.run_job(job, ctx)          # P3.4 needs the crops and embeddings
        if _models is None:
            _models = faces.Models(cache, vram_mb=ctx.get("vram_mb"))
        payload = dict(job.get("payload") or {}, path=job.get("path"))
        result = analyse(_models, conn, job["key"], payload)
        save(cache, job["key"], result)
    finally:
        conn.close()
    return {"score": result.get("score"), "drift": result["drift"].get("flagged"), "ms": result["ms"]}
