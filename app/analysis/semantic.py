"""P4.1 semantic search: SigLIP embeddings of the P3.1 sampled frames.

Per clip:   app/.cache/semantic/<key>.npy   float16 (frames x 768), L2-normalised
            app/.cache/semantic/<key>.json  {"path", "times"}
Library:    app/.cache/semantic/index.npy   float16 matrix of every frame (rebuilt when stale)
            app/.cache/semantic/index.json  {"keys", "paths", "offsets", "times"}

The text encoder lives here, in the add-on worker; the core (stdlib only) asks
for a query over a loopback HTTP socket the worker opens on 127.0.0.1
(port published in app/.cache/semantic/port.json). Model weights are fetched
once from Hugging Face into app/.cache/models/ (Apache-2.0, docs/MODELS.md).
"""

import json
import os
import threading
import time
import unicodedata
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

from analysis import frames

MODEL_ID = "google/siglip-base-patch16-224"
BATCH = 8
OFFLOAD_AFTER = 60.0  # seconds without image work -> move the model off the GPU (C5)
TEXT_LEN = 64  # SigLIP was trained with max_length padding to 64 tokens


def canonical(text):
    """SiglipTokenizer's text canonicalisation: lowercase, no punctuation, single spaces."""
    text = "".join(" " if unicodedata.category(c).startswith("P") else c for c in str(text).lower())
    return " ".join(text.split())


def sem_dir(cache_dir):
    return Path(cache_dir) / "semantic"


def _tensor(out):
    """transformers >= 5 returns a ModelOutput from get_*_features; the embedding is its pooler_output."""
    return out if hasattr(out, "norm") else out.pooler_output


class Model:
    """Lazily loaded SigLIP. fp16 on CUDA while analysing, fp32 on CPU otherwise."""

    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir)
        self.lock = threading.RLock()
        self.model = self.processor = None
        self.device = "cpu"
        self.last_gpu = 0.0

    def _load(self):
        if self.model is not None:
            return
        from huggingface_hub import snapshot_download
        from tokenizers import Tokenizer
        from transformers import SiglipImageProcessor, SiglipModel
        models = self.cache_dir / "models"
        models.mkdir(parents=True, exist_ok=True)
        kwargs = {"cache_dir": str(models), "allow_patterns": ["*.json", "*.safetensors", "*.model"]}
        try:
            local = snapshot_download(MODEL_ID, local_files_only=True, **kwargs)
        except Exception:  # first run: one-time download
            local = snapshot_download(MODEL_ID, **kwargs)
        self.processor = SiglipImageProcessor.from_pretrained(local)
        self.model = SiglipModel.from_pretrained(local).eval()
        # tokenizer.json via `tokenizers` (ships with transformers) - no sentencepiece needed.
        self.tokenizer = Tokenizer.from_file(str(Path(local) / "tokenizer.json"))
        pad = self.tokenizer.token_to_id("</s>")
        self.tokenizer.enable_truncation(TEXT_LEN)
        self.tokenizer.enable_padding(length=TEXT_LEN, pad_id=pad, pad_token="</s>")

    def to(self, want_gpu):
        import torch
        with self.lock:
            self._load()
            device = "cuda" if want_gpu and torch.cuda.is_available() else "cpu"
            if device != self.device:
                self.model.to(device=device, dtype=torch.float16 if device == "cuda" else torch.float32)
                if device == "cpu" and torch.cuda.is_available():
                    torch.cuda.empty_cache()
                self.device = device
            if device == "cuda":
                self.last_gpu = time.monotonic()

    def idle(self):
        if self.device == "cuda" and time.monotonic() - self.last_gpu > OFFLOAD_AFTER:
            self.to(False)

    def images(self, paths):
        import torch
        from PIL import Image
        out = []
        with self.lock, torch.inference_mode():
            self.to(True)
            dtype = next(self.model.parameters()).dtype
            for i in range(0, len(paths), BATCH):
                imgs = [Image.open(p).convert("RGB") for p in paths[i:i + BATCH]]
                pix = self.processor(images=imgs, return_tensors="pt")["pixel_values"]
                feats = _tensor(self.model.get_image_features(pixel_values=pix.to(self.device, dtype)))
                feats = feats / feats.norm(dim=-1, keepdim=True)
                out.append(feats.float().cpu().numpy())
            self.last_gpu = time.monotonic()
        return np.concatenate(out).astype(np.float16)

    def texts(self, texts):
        import torch
        with self.lock, torch.inference_mode():
            self._load()
            ids = [e.ids for e in self.tokenizer.encode_batch([canonical(t) for t in texts])]
            feats = _tensor(self.model.get_text_features(input_ids=torch.tensor(ids, device=self.device)))
            feats = feats / feats.norm(dim=-1, keepdim=True)
            return feats.float().cpu().numpy()

    def calibration(self):
        """(scale, bias) so sigmoid(scale * cos + bias) is SigLIP's match probability."""
        self._load()
        return float(self.model.logit_scale.detach().exp()), float(self.model.logit_bias.detach())


_models = {}


def get_model(cache_dir):
    key = str(cache_dir)
    if key not in _models:
        _models[key] = Model(cache_dir)
    return _models[key]


def load_clip(cache_dir, key):
    folder = sem_dir(cache_dir)
    try:
        meta = json.loads((folder / f"{key}.json").read_text(encoding="utf-8"))
        return np.load(folder / f"{key}.npy"), meta
    except (OSError, ValueError):
        return None, None


def embed_clip(job, ctx):
    """Embeddings for one clip (cached by key, C6). Samples frames first if P3.1 has not yet."""
    cache = ctx["cache"]
    emb, meta = load_clip(cache, job["key"])
    if emb is not None:
        return emb, meta, True
    manifest = frames.load(cache, job["key"])
    if not manifest:
        frames.sample(ctx.get("ffmpeg"), job["path"], cache, job["key"],
                      duration=(job.get("payload") or {}).get("duration"))
        manifest = frames.load(cache, job["key"])
    emb = get_model(cache).images(manifest["paths"])
    meta = {"path": job["path"], "times": manifest.get("times") or list(range(len(emb)))}
    folder = sem_dir(cache)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f"{job['key']}.tmp{os.getpid()}.npy"
    np.save(tmp, emb)
    os.replace(tmp, folder / f"{job['key']}.npy")
    (folder / f"{job['key']}.json").write_text(json.dumps(meta), encoding="utf-8")
    return emb, meta, False


def run_job(job, ctx):
    """Worker handler for kind 'semantic'."""
    started = time.perf_counter()
    emb, _, cached = embed_clip(job, ctx)
    return {"frames": int(emb.shape[0]), "cached": cached, "ms": round((time.perf_counter() - started) * 1000)}


# ------------------------------------------------------------------ library index
class Index:
    """All frame embeddings as one matrix; per-clip max over its frames."""

    def __init__(self, matrix, keys, paths, offsets, times):
        self.matrix = np.ascontiguousarray(matrix, dtype=np.float16)
        self.keys, self.paths, self.times = keys, paths, times
        self.offsets = np.asarray(offsets, dtype=np.int64)
        self._f32 = None

    def scores(self, query):
        # numpy has no fast fp16 GEMM: keep a float32 copy (built once per index).
        if self._f32 is None:
            self._f32 = self.matrix.astype(np.float32)
        return self._f32 @ np.asarray(query, dtype=np.float32)

    def top(self, query, k=50, allowed=None):
        if not len(self.keys):
            return []
        sims = self.scores(query)
        best = np.maximum.reduceat(sims, self.offsets)
        if allowed is not None:
            mask = np.array([p in allowed for p in self.paths])
            best = np.where(mask, best, -np.inf)
        k = min(k, len(best))
        order = np.argpartition(-best, k - 1)[:k]
        order = order[np.argsort(-best[order])]
        ends = list(self.offsets[1:]) + [len(sims)]
        out = []
        for c in order:
            if not np.isfinite(best[c]):
                continue
            lo, hi = int(self.offsets[c]), int(ends[c])
            frame = int(np.argmax(sims[lo:hi]))
            times = self.times[c]
            out.append({"key": self.keys[c], "path": self.paths[c], "frame": frame,
                        "time": float(times[frame]) if frame < len(times) else 0.0, "cos": float(best[c])})
        return out


def build_index(cache_dir):
    folder = sem_dir(cache_dir)
    keys, paths, times, mats, offsets, n = [], [], [], [], [], 0
    for npy in sorted(folder.glob("*.npy")):
        key = npy.stem
        if key == "index" or ".tmp" in key:
            continue
        emb, meta = load_clip(cache_dir, key)
        if emb is None or not len(emb):
            continue
        keys.append(key), paths.append(meta["path"]), times.append(meta["times"])
        offsets.append(n), mats.append(emb)
        n += len(emb)
    matrix = np.concatenate(mats) if mats else np.zeros((0, 768), np.float16)
    np.save(folder / "index.tmp.npy", matrix)
    os.replace(folder / "index.tmp.npy", folder / "index.npy")
    (folder / "index.json").write_text(json.dumps(
        {"keys": keys, "paths": paths, "offsets": offsets, "times": times}), encoding="utf-8")
    return Index(matrix, keys, paths, offsets, times)


class Searcher:
    def __init__(self, cache_dir, model=None):
        self.cache_dir = Path(cache_dir)
        self.model = model or get_model(cache_dir)
        self.index, self.stamp = None, None
        self.lock = threading.Lock()

    def _stamp(self):
        folder = sem_dir(self.cache_dir)
        try:
            return (folder.stat().st_mtime_ns, sum(1 for _ in folder.glob("*.npy")))
        except OSError:
            return None

    def current(self):
        with self.lock:
            stamp = self._stamp()
            if self.index is None or stamp != self.stamp:
                sem_dir(self.cache_dir).mkdir(parents=True, exist_ok=True)
                self.index = build_index(self.cache_dir)
                self.stamp = self._stamp()
            return self.index

    def search(self, text, k=50, allowed=None):
        started = time.perf_counter()
        index = self.current()
        query = self.model.texts([text])[0]
        t_text = time.perf_counter()
        hits = index.top(query, k=k, allowed=allowed)
        scale, bias = self.model.calibration()
        for hit in hits:
            hit["score"] = round(float(1 / (1 + np.exp(-(scale * hit.pop("cos") + bias)))), 5)
        return {"results": hits, "clips": len(index.keys), "frames": int(index.matrix.shape[0]),
                "ms_text": round((t_text - started) * 1000, 1),
                "ms_total": round((time.perf_counter() - started) * 1000, 1)}


# ------------------------------------------------------------------ loopback server
def serve(ctx, host="127.0.0.1", port=0):
    """Start the query socket in a daemon thread; publish its port for the core."""
    searcher = Searcher(ctx["cache"])
    ctx["searcher"] = searcher

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            try:
                if parsed.path == "/search":
                    body = searcher.search((qs.get("q") or [""])[0][:200], k=int((qs.get("k") or ["50"])[0]))
                elif parsed.path == "/ping":
                    body = {"ok": True}
                else:
                    self.send_error(404)
                    return
                status = 200
            except Exception as error:  # report, never crash the worker
                body, status = {"error": f"{type(error).__name__}: {error}"}, 500
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # Warm the index (and its float32 copy) so the first query is not the slow one.
    threading.Thread(target=lambda: searcher.current().scores(np.zeros(searcher.current().matrix.shape[1])),
                     daemon=True).start()
    folder = sem_dir(ctx["cache"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "port.json").write_text(json.dumps({"port": server.server_address[1], "pid": os.getpid()}),
                                      encoding="utf-8")
    return server
