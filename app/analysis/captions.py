"""P4.3 captions and prompt adherence from a local vision model (opt-in, off by default).

Nothing leaves the machine: the endpoint must be loopback (C3), and the job only runs when
a settings file names a model, because asking an LLM server for a model it has not loaded
makes some servers (LM Studio) load it, which fights WanGP for VRAM. Off by default.

Settings live in app/.data/captions.json (user-authored, Reset keeps it):
    {"endpoint": "http://127.0.0.1:1234/v1", "model": "<id from `lms ps`>", "frames": 3}

Per clip result in app/.cache/captions/<key>.json:
    {"path", "captions": [{"frame", "t", "text"}], "adherence": 0..100|null, "model", "ms"}
Adherence is the cosine between the SigLIP text embedding of the caption and of the clip's
prompt, mapped with the same band as the reference score (0.2 -> 0, 0.8 -> 100).
"""

import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from analysis import frames

VERSION = 1
DEFAULT_FRAMES = 3
MAX_CAPTION_CHARS = 400
COS_FLOOR = 0.2
COS_CEIL = 0.8
LOOPBACK = {"127.0.0.1", "localhost", "::1"}

PROMPT = ("Describe this video frame in one short sentence: who is in it, what they are doing "
          "and where. No preamble, no lists.")


class NotConfigured(RuntimeError):
    pass


class BadEndpoint(RuntimeError):
    pass


def settings_path(app_dir):
    return Path(app_dir) / ".data" / "captions.json"


def load_settings(app_dir):
    try:
        return json.loads(settings_path(app_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def check_endpoint(endpoint):
    """C3: only a loopback endpoint may ever be contacted."""
    host = (urlparse(str(endpoint or "")).hostname or "").strip("[]")
    if host not in LOOPBACK:
        raise BadEndpoint(f"captions need a loopback endpoint, not {host or 'an empty URL'}")
    return str(endpoint).rstrip("/")


def captions_dir(cache_dir):
    return Path(cache_dir) / "captions"


def pick_frames(manifest, count=DEFAULT_FRAMES):
    paths = manifest.get("paths") or []
    times = manifest.get("times") or []
    if not paths:
        return []
    if len(paths) <= count:
        chosen = list(range(len(paths)))
    else:                                  # spread across the clip, not just the opening
        step = (len(paths) - 1) / (count - 1)
        chosen = [int(round(i * step)) for i in range(count)]
    return [{"frame": i, "t": times[i] if i < len(times) else None, "path": paths[i]} for i in chosen]


def _post(endpoint, model, prompt, image_bytes, timeout=120.0):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")}},
        ]}],
        "max_tokens": 120,
        "temperature": 0,
    }
    request = urllib.request.Request(f"{endpoint}/chat/completions", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    message = (body.get("choices") or [{}])[0].get("message") or {}
    text = (message.get("content") or "").strip()
    return text[:MAX_CAPTION_CHARS]


def adherence(text_encoder, caption, prompt):
    """Cosine between caption and prompt in the SigLIP text space, mapped to 0..100."""
    if not caption or not prompt or text_encoder is None:
        return None
    vectors = text_encoder([caption, prompt])
    if vectors is None or len(vectors) != 2:
        return None
    import numpy as np

    a, b = (v / (np.linalg.norm(v) or 1.0) for v in vectors)
    cos = float(np.dot(a, b))
    value = (cos - COS_FLOOR) / (COS_CEIL - COS_FLOOR)
    return round(max(0.0, min(1.0, value)) * 100.0, 1)


def analyse(cache_dir, key, path, settings, text_encoder=None, manifest=None):
    started = time.monotonic()
    endpoint = check_endpoint(settings.get("endpoint"))
    model = settings.get("model")
    if not model:
        raise NotConfigured("set a model id in app/.data/captions.json (see `lms ps`)")
    manifest = manifest or frames.load(cache_dir, key) or {}
    prompt = manifest.get("prompt") or ""
    out = []
    for item in pick_frames(manifest, int(settings.get("frames") or DEFAULT_FRAMES)):
        try:
            image = Path(item["path"]).read_bytes()
        except OSError:
            continue
        try:
            text = _post(endpoint, model, PROMPT, image)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as error:
            out.append({"frame": item["frame"], "t": item["t"], "error": str(error)[:160]})
            continue
        out.append({"frame": item["frame"], "t": item["t"], "text": text,
                    "adherence": adherence(text_encoder, text, prompt)})
    scored = [c["adherence"] for c in out if isinstance(c.get("adherence"), (int, float))]
    result = {"path": str(path), "version": VERSION, "model": model, "captions": out,
              "prompt": prompt[:400],
              "adherence": round(sum(scored) / len(scored), 1) if scored else None,
              "ms": int((time.monotonic() - started) * 1000)}
    return result


def save(cache_dir, key, result):
    folder = captions_dir(cache_dir)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{key}.json"
    tmp = target.with_name(f"{target.name}.tmp")
    tmp.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    tmp.replace(target)


def load(cache_dir, key):
    try:
        return json.loads((captions_dir(cache_dir) / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_job(job, ctx):
    """Worker handler for kind 'captions'. Silent no-op when the feature is not configured."""
    cache = Path(ctx["cache"])
    settings = ctx.get("captions") or load_settings(Path(cache).parent)
    if not settings.get("model"):
        return {"skipped": "not configured"}
    done = load(cache, job["key"])
    if done and done.get("version") == VERSION and done.get("model") == settings.get("model"):
        return {"adherence": done.get("adherence"), "cached": True}
    encoder = ctx.get("text_encoder")
    if encoder is None:
        try:  # reuse the P4.1 SigLIP text tower when the add-on has it
            from analysis import semantic
            model = semantic.get_model(Path(cache))
            encoder = lambda texts: model.texts(texts)  # noqa: E731
        except Exception:  # noqa: BLE001 - adherence is optional, captions are not
            encoder = None
    result = analyse(cache, job["key"], job["path"], settings, text_encoder=encoder)
    save(cache, job["key"], result)
    return {"adherence": result["adherence"], "captions": len(result["captions"])}
