"""P4.2 auto-tags: zero-shot SigLIP labels + camera motion from optical flow.

Vocabulary: app/analysis/tags.yaml (JSON-compatible YAML, so the stdlib core can
read it too). Per clip result in app/.cache/tags/<key>.json:
    {"path", "tags": {group: label}, "scores": {group: {label: prob}}, "motion": {...}}
Reuses the P4.1 frame embeddings (computes them if the semantic job has not run).
The source video is only read (C4).
"""

import json
import os
import time
from pathlib import Path

import numpy as np

from analysis import frames, semantic

VOCAB_PATH = Path(__file__).resolve().parent / "tags.yaml"


def load_vocab(path=VOCAB_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def tags_dir(cache_dir):
    return Path(cache_dir) / "tags"


_text_cache = {}


def label_embeddings(model, vocab):
    """{group: (labels, matrix)} - prompt-ensemble text embeddings, built once per process."""
    key = (id(model), json.dumps(vocab["groups"], sort_keys=True))
    if key not in _text_cache:
        out = {}
        for group in vocab["groups"]:
            labels = list(group["labels"])
            rows = []
            for label in labels:
                emb = model.texts(group["labels"][label]).mean(axis=0)
                rows.append(emb / np.linalg.norm(emb))
            out[group["id"]] = (labels, np.stack(rows))
        _text_cache[key] = out
    return _text_cache[key]


def zero_shot(frame_emb, text, scale, bias):
    """Best label per group from the clip's mean frame/label similarity."""
    tags, scores = {}, {}
    emb = frame_emb.astype(np.float32)
    for gid, (labels, mat) in text.items():
        cos = (emb @ mat.T).mean(axis=0)
        probs = 1 / (1 + np.exp(-(scale * cos + bias)))
        tags[gid] = labels[int(np.argmax(cos))]
        scores[gid] = {label: round(float(p), 5) for label, p in zip(labels, probs)}
    return tags, scores


# ------------------------------------------------------------------ camera motion
def _gray(img, width):
    import cv2
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = img.shape
    return cv2.resize(img, (width, max(8, int(round(h * width / w)))), interpolation=cv2.INTER_AREA)


def classify_flow(flow, cfg):
    """One flow field (H x W x 2, pixels) -> (label, stats). Camera estimated from the border ring,
    the centre (usually the subject) only decides pan vs orbit."""
    h, w = flow.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w]
    xn, yn = xs / w - 0.5, ys / h - 0.5
    border = (np.abs(xn) > 0.3) | (np.abs(yn) > 0.3)
    centre = (np.abs(xn) < 0.17) & (np.abs(yn) < 0.25)
    u, v = flow[..., 0] / w, flow[..., 1] / w
    mag = np.hypot(u, v)
    stats = {"mag": float(np.median(mag[border]))}
    if stats["mag"] < cfg["static_below"]:
        return "static", stats
    a = np.stack([np.ones(border.sum()), xn[border], yn[border]], axis=1)
    cu = np.linalg.lstsq(a, u[border], rcond=None)[0]
    cv = np.linalg.lstsq(a, v[border], rcond=None)[0]
    tx, ty, div = float(cu[0]), float(cv[0]), float((cu[1] + cv[2]) / 2)
    stats.update(tx=tx, ty=ty, div=div)
    # zoom: edge displacement from divergence outweighs any translation
    if abs(div) > cfg["zoom_divergence"] and abs(div) * 0.5 > float(np.hypot(tx, ty)):
        return "zoom", stats
    if abs(tx) >= abs(ty):
        side = float(np.mean(u[border & (np.abs(xn) > 0.3)]))
        mid = float(np.mean(u[centre]))
        parallax = abs(side - mid) / max(abs(side), abs(mid), 1e-6)
        stats["parallax"] = parallax
        if parallax > cfg["orbit_parallax"] and abs(mid) < abs(side):
            return "orbit", stats
        return "pan", stats
    return "tilt", stats


def _pairs_from_video(path, cfg):
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        step, n = int(cfg["step_frames"]), int(cfg["pairs"])
        if not cap.isOpened() or total < step + 2:
            return []
        out = []
        for i in range(n):
            pos = int((total - step - 1) * (i + 0.5) / n)
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ok, a = cap.read()
            for _ in range(step):
                ok2, b = cap.read()
            if ok and ok2:
                out.append((_gray(a, cfg["width"]), _gray(b, cfg["width"])))
        return out
    finally:
        cap.release()


def _pairs_from_frames(paths, cfg):
    import cv2
    imgs = [_gray(cv2.imread(p), cfg["width"]) for p in paths[: cfg["pairs"] + 1]]
    return list(zip(imgs, imgs[1:]))


def camera_motion(path, frame_paths, cfg):
    import cv2
    pairs = _pairs_from_video(path, cfg) or _pairs_from_frames(frame_paths, cfg)
    votes, per = {}, []
    for a, b in pairs:
        if a.shape != b.shape:
            continue
        flow = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        label, stats = classify_flow(flow, cfg)
        votes[label] = votes.get(label, 0) + 1
        per.append(label)
    if not votes:
        return "static", {"pairs": 0}
    label = max(votes, key=lambda k: (votes[k], k != "static"))
    return label, {"pairs": len(per), "votes": votes}


def run_job(job, ctx):
    """Worker handler for kind 'tags'."""
    started = time.perf_counter()
    cache = ctx["cache"]
    out_path = tags_dir(cache) / f"{job['key']}.json"
    if out_path.is_file():
        return {"cached": True}
    vocab = load_vocab(ctx.get("tags_vocab", VOCAB_PATH))
    emb, _, _ = semantic.embed_clip(job, ctx)
    model = semantic.get_model(cache)
    tags, scores = zero_shot(emb, label_embeddings(model, vocab), *model.calibration())
    t_zero = time.perf_counter()
    manifest = frames.load(cache, job["key"]) or {"paths": []}
    motion, motion_info = camera_motion(job["path"], manifest["paths"], vocab["motion"])
    tags["motion"] = motion
    result = {"path": job["path"], "tags": tags, "scores": scores, "motion": motion_info}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(f"{job['key']}.tmp{os.getpid()}")
    tmp.write_text(json.dumps(result), encoding="utf-8")
    os.replace(tmp, out_path)
    return {"tags": tags, "ms_zero_shot": round((t_zero - started) * 1000),
            "ms_motion": round((time.perf_counter() - t_zero) * 1000)}
