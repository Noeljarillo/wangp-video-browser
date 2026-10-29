"""P3.2 face and person detection plus identity embeddings (worker side, add-on venv).

Per clip, on the P3.1 sampled frames (frames.load):
  * faces   - OpenCV YuNet detector (MIT) + SFace recogniser (Apache-2.0), 128-d embedding
              of the aligned face. CPU via cv2.dnn: tiny models, a few ms per frame.
  * persons - torchvision Faster R-CNN MobileNetV3-Large FPN (BSD-3, COCO 'person'),
              plus a DINOv2-small (Apache-2.0) 384-d CLS embedding of every person crop,
              which also covers stylised / anime / non-human characters SFace can't.
Torch work runs on CUDA in fp16 when available (small batches, memory released after
each clip, per-process VRAM fraction capped to the worker's --vram-mb) and falls back
to CPU. Weights are read from app/.cache/models/ only - no network at runtime (C3);
`python -m analysis.faces --download` fetches them once (licences: docs/MODELS.md).
A small JPEG crop per detection is written to app/.cache/faces/<key>/<n>.jpg for the
Characters view. Source videos are never touched (C4).
"""

import argparse
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis import detstore, frames  # noqa: E402

MODELS = {
    "yunet": ("face_detection_yunet_2023mar.onnx",
              "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"),
    "sface": ("face_recognition_sface_2021dec.onnx",
              "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"),
    "person": ("fasterrcnn_mobilenet_v3_large_fpn-fb6a3cc7.pth",
               "https://download.pytorch.org/models/fasterrcnn_mobilenet_v3_large_fpn-fb6a3cc7.pth"),
    "dinov2/config.json": ("dinov2-small/config.json",
                           "https://huggingface.co/facebook/dinov2-small/resolve/main/config.json"),
    "dinov2/model.safetensors": ("dinov2-small/model.safetensors",
                                 "https://huggingface.co/facebook/dinov2-small/resolve/main/model.safetensors"),
}
MODEL_IDS = {"face": "sface-2021dec", "person": "dinov2-small"}

FACE_SCORE = 0.8
FACE_MIN_PX = 24
PERSON_SCORE = 0.6
PERSON_MIN_FRAC = 0.04     # ignore people smaller than 4 % of the frame height
MAX_PERSONS = 6            # per frame
BATCH = 4                  # frames per detector batch (keeps VRAM small)
CROP_PX = 128


def models_dir(cache_dir):
    return Path(cache_dir) / "models"


def missing_models(cache_dir):
    return [name for name, (rel, _) in MODELS.items() if not (models_dir(cache_dir) / rel).is_file()]


def download(cache_dir):
    """One-time fetch of the weights (install step, never called by the worker)."""
    for name, (rel, url) in MODELS.items():
        target = models_dir(cache_dir) / rel
        if target.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")
        print(f"[faces] downloading {name}", flush=True)
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(target)


class Models:
    """Lazily loaded once per worker process; kept across clips."""

    def __init__(self, cache_dir, vram_mb=None):
        import cv2
        import torch
        import torchvision
        from transformers import AutoModel

        missing = missing_models(cache_dir)
        if missing:
            raise RuntimeError("analysis models missing (run Install analysis): " + ", ".join(missing))
        root = models_dir(cache_dir)
        self.cv2, self.torch = cv2, torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        if self.device == "cuda" and vram_mb:
            total = torch.cuda.get_device_properties(0).total_memory / 2**20
            torch.cuda.set_per_process_memory_fraction(min(1.0, vram_mb / total))
        self.yunet = cv2.FaceDetectorYN.create(str(root / MODELS["yunet"][0]), "", (320, 320),
                                               FACE_SCORE, 0.3, 50)
        self.sface = cv2.FaceRecognizerSF.create(str(root / MODELS["sface"][0]), "")
        det = torchvision.models.detection.fasterrcnn_mobilenet_v3_large_fpn(
            weights=None, weights_backbone=None, num_classes=91, box_score_thresh=PERSON_SCORE)
        det.load_state_dict(torch.load(root / MODELS["person"][0], map_location="cpu", weights_only=True))
        self.det = det.eval().to(self.device)
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.dino = AutoModel.from_pretrained(str(root / "dinov2-small"), dtype=dtype).eval().to(self.device)
        self.dtype = dtype
        mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
        self.mean, self.std = mean.to(self.device, dtype), std.to(self.device, dtype)

    # -- faces (cv2, CPU) ----------------------------------------------------
    def faces(self, img):
        h, w = img.shape[:2]
        self.yunet.setInputSize((w, h))
        _, found = self.yunet.detect(img)
        out = []
        for row in (found if found is not None else []):
            x, y, fw, fh, score = float(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[14])
            if min(fw, fh) < FACE_MIN_PX:
                continue
            aligned = self.sface.alignCrop(img, row)
            feat = self.sface.feature(aligned).flatten()
            out.append({"box": (x, y, fw, fh), "score": score, "emb": _l2(feat), "crop": aligned})
        return out

    # -- persons (torch) -----------------------------------------------------
    def persons(self, images):
        torch = self.torch
        tensors = [torch.from_numpy(im[:, :, ::-1].copy()).permute(2, 0, 1).float().div(255).to(self.device)
                   for im in images]
        with torch.inference_mode():
            if self.device == "cuda":
                with torch.autocast("cuda", dtype=torch.float16):
                    preds = self.det(tensors)
            else:
                preds = self.det(tensors)
        out = []
        for img, pred in zip(images, preds):
            h = img.shape[0]
            keep = []
            for box, label, score in zip(pred["boxes"].tolist(), pred["labels"].tolist(), pred["scores"].tolist()):
                if label != 1 or score < PERSON_SCORE or (box[3] - box[1]) < PERSON_MIN_FRAC * h:
                    continue
                keep.append({"box": (box[0], box[1], box[2] - box[0], box[3] - box[1]), "score": score})
            out.append(keep[:MAX_PERSONS])
        return out

    def embed_crops(self, crops):
        """DINOv2-small CLS embeddings of BGR crops (224 px, ImageNet norm)."""
        if not crops:
            return []
        torch, cv2 = self.torch, self.cv2
        vectors = []
        for start in range(0, len(crops), 16):
            chunk = [cv2.resize(c, (224, 224), interpolation=cv2.INTER_AREA)[:, :, ::-1] for c in crops[start:start + 16]]
            batch = torch.from_numpy(_stack(chunk)).permute(0, 3, 1, 2).to(self.device, self.dtype).div(255)
            batch = (batch - self.mean) / self.std
            with torch.inference_mode():
                cls = self.dino(pixel_values=batch).last_hidden_state[:, 0]
            vectors.extend(torch.nn.functional.normalize(cls.float(), dim=1).cpu().tolist())
        return vectors

    def release(self):
        if self.device == "cuda":
            self.torch.cuda.empty_cache()


def _l2(vec):
    import numpy as np
    vec = np.asarray(vec, dtype="float32")
    norm = float(np.linalg.norm(vec)) or 1.0
    return (vec / norm).tolist()


def _stack(images):
    import numpy as np
    return np.ascontiguousarray(np.stack(images))


def _crop(img, box, pad=0.0):
    h, w = img.shape[:2]
    x, y, bw, bh = box
    x0, y0 = max(0, int(x - pad * bw)), max(0, int(y - pad * bh))
    x1, y1 = min(w, int(x + bw * (1 + pad))), min(h, int(y + bh * (1 + pad)))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return img[y0:y1, x0:x1]


def crops_dir(cache_dir, key):
    return Path(cache_dir) / "faces" / key


def analyse(models, cache_dir, key, manifest):
    """Detect + embed on every sampled frame. Returns (rows, run_info)."""
    cv2 = models.cv2
    started = time.monotonic()
    images = [cv2.imread(p) for p in manifest["paths"]]
    times = manifest.get("times") or []
    rows, crops = [], []
    persons = []
    for start in range(0, len(images), BATCH):
        persons.extend(models.persons([im for im in images[start:start + BATCH] if im is not None]))
    person_crops, person_meta = [], []
    pi = 0
    for fi, img in enumerate(images):
        if img is None:
            continue
        h, w = img.shape[:2]
        t = times[fi] if fi < len(times) else None
        for face in models.faces(img):
            x, y, bw, bh = face["box"]
            rows.append({"frame": fi, "t": t, "kind": "face", "x": x / w, "y": y / h, "w": bw / w, "h": bh / h,
                         "score": round(face["score"], 4), "model": MODEL_IDS["face"], "emb": face["emb"]})
            crops.append(_crop(img, face["box"], pad=0.25))
        for person in persons[pi]:
            crop = _crop(img, person["box"])
            if crop is None:
                continue
            x, y, bw, bh = person["box"]
            person_crops.append(crop)
            person_meta.append({"frame": fi, "t": t, "kind": "person", "x": x / w, "y": y / h, "w": bw / w,
                                "h": bh / h, "score": round(person["score"], 4), "model": MODEL_IDS["person"]})
        pi += 1
    for meta, vec, crop in zip(person_meta, models.embed_crops(person_crops), person_crops):
        rows.append(dict(meta, emb=vec))
        crops.append(crop)
    folder = crops_dir(cache_dir, key)
    folder.mkdir(parents=True, exist_ok=True)
    for n, (row, crop) in enumerate(zip(rows, crops)):
        row["n"] = n
        row.update({k: round(row[k], 5) for k in ("x", "y", "w", "h")})
        if crop is not None:
            ch, cw = crop.shape[:2]
            scale = CROP_PX / max(ch, cw)
            small = cv2.resize(crop, (max(1, int(cw * scale)), max(1, int(ch * scale))), interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(folder / f"{n}.jpg"), small, [cv2.IMWRITE_JPEG_QUALITY, 85])
    models.release()
    run = {"frames": len(images), "faces": sum(r["kind"] == "face" for r in rows),
           "persons": sum(r["kind"] == "person" for r in rows), "ms": int((time.monotonic() - started) * 1000),
           "device": models.device, "models": dict(MODEL_IDS, detector="fasterrcnn_mobilenet_v3_large_fpn",
                                                   face_detector="yunet-2023mar")}
    return rows, run


_models = None


def run_job(job, ctx):
    """Worker handler for kind 'faces'. Needs the clip's 'frames' job done first."""
    global _models
    cache = Path(ctx["cache"])
    conn = detstore.connect(ctx.get("db") or cache / "analysis.db")
    try:
        done = detstore.run_info(conn, job["key"])
        if done:  # C6: same key -> never redone
            return dict({k: done[k] for k in ("frames", "faces", "persons", "ms", "device")}, cached=True)
        manifest = frames.load(cache, job["key"])
        if not manifest:
            raise RuntimeError("no sampled frames for this clip yet")
        if _models is None:
            _models = Models(cache, vram_mb=ctx.get("vram_mb"))
        rows, run = analyse(_models, cache, job["key"], manifest)
        detstore.save(conn, job["key"], rows, run)
    finally:
        conn.close()
    return {k: run[k] for k in ("frames", "faces", "persons", "ms", "device")}


def main():
    parser = argparse.ArgumentParser(description="Face / person detection (P3.2)")
    parser.add_argument("--cache", default=str(Path(__file__).resolve().parent.parent / ".cache"))
    parser.add_argument("--download", action="store_true", help="fetch model weights into <cache>/models")
    args = parser.parse_args()
    if args.download:
        download(args.cache)
    print("missing:", missing_models(args.cache) or "none")


if __name__ == "__main__":
    main()
