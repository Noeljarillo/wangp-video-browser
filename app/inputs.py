"""
Input references (P1.3): the start/end frames, reference images and guide
media a clip was generated from.

Sources, in order:
  * WanGP settings keys (`image_start`, `image_refs`, `video_guide`, ...) that
    hold file paths (older WanGP builds and other tools keep them);
  * ComfyUI `LoadImage` / video loader nodes in the embedded API graph;
  * images WanGP embedded in the MP4 itself (`embed_source_images` option,
    `----:com.apple.iTunes:EMBEDDED_IMAGES` + `IMAGE_METADATA`).

Serving is allow-list only: `/input/<id>/<n>` can return nothing but the n-th
reference *this clip's metadata* names, and only if that file exists. No path
from the request is ever joined onto the filesystem.
"""

import json
import os
import threading
from pathlib import Path

import metadata as meta_reader

# WanGP's ATTACHMENT_KEYS (wgp.py), in the order WanGP shows them.
WANGP_KEYS = (
    "image_start", "image_end", "image_refs", "image_guide", "image_mask",
    "video_source", "video_guide", "video_guide2", "video_guide3", "video_mask",
    "audio_guide", "audio_guide2", "audio_guide3", "audio_source",
    "replace_voice_sample", "replace_voice_sample2", "custom_guide",
)
LABELS = {
    "image_start": "Start frame", "image_end": "End frame", "image_refs": "Reference",
    "image_guide": "Guide image", "image_mask": "Mask image", "video_source": "Source video",
    "video_guide": "Guide video", "video_guide2": "Guide video 2", "video_guide3": "Guide video 3",
    "video_mask": "Mask video", "audio_guide": "Guide audio", "audio_guide2": "Guide audio 2",
    "audio_guide3": "Guide audio 3", "audio_source": "Source audio",
    "replace_voice_sample": "Voice sample", "replace_voice_sample2": "Voice sample 2",
    "custom_guide": "Custom guide", "comfy_image": "LoadImage", "comfy_video": "LoadVideo",
}
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")
VIDEO_EXT = (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi")
AUDIO_EXT = (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac")
COMFY_LOADERS = {"LoadImage": "image", "LoadImageMask": "image", "LoadImageOutput": "image",
                 "LoadVideo": "video", "VHS_LoadVideo": "video", "VHS_LoadVideoPath": "video"}
EMBED_NAME, EMBED_META = "EMBEDDED_IMAGES", "IMAGE_METADATA"

_embed_cache = {}
_embed_lock = threading.Lock()


def kind_of(name):
    lower = str(name).lower()
    if lower.endswith(IMAGE_EXT):
        return "image"
    if lower.endswith(VIDEO_EXT):
        return "video"
    if lower.endswith(AUDIO_EXT):
        return "audio"
    return "file"


def _strings(value):
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [v for v in value if isinstance(v, str) and v.strip()]
    return []


def _resolve(raw, entry, extra_dirs=()):
    """First existing file among the plausible readings of a recorded path."""
    raw = raw.strip()
    path = Path(raw).expanduser()
    candidates = [path] if path.is_absolute() else []
    if not path.is_absolute():
        clip_dir = Path(entry["path"]).parent
        root = Path(entry.get("root") or clip_dir)
        candidates += [d / path for d in (*extra_dirs, root.parent, root, clip_dir)]
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


# -- embedded MP4 images -----------------------------------------------------

def _embedded_index(path):
    """[(tag, filename, offset, length, mime)] for images WanGP put in the MP4."""
    found = {"images": [], "meta": None}

    def walk(handle, start, end, depth):
        if depth > 6:
            return
        for box, body, box_end in meta_reader._iter_boxes(handle, start, end):
            if box in (b"moov", b"udta", b"ilst"):
                walk(handle, body, box_end, depth + 1)
            elif box == b"meta":
                handle.seek(body + 4)
                walk(handle, body if handle.read(4) == b"hdlr" else body + 4, box_end, depth + 1)
            elif box == b"----":
                name, datas = None, []
                for inner, ibody, iend in meta_reader._iter_boxes(handle, body, box_end):
                    if inner == b"name":
                        handle.seek(ibody + 4)
                        name = handle.read(max(0, iend - ibody - 4)).decode("utf-8", "ignore")
                    elif inner == b"data":
                        handle.seek(ibody)
                        type_code = int.from_bytes(handle.read(4)[1:], "big")
                        datas.append((ibody + 8, iend - ibody - 8, type_code))
                if name == EMBED_NAME:
                    found["images"] = datas
                elif name == EMBED_META and datas:
                    handle.seek(datas[0][0])
                    found["meta"] = handle.read(min(datas[0][1], 1 << 20))

    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            walk(handle, 0, size, 0)
    except OSError:
        return []
    images = found["images"]
    if not images:
        return []
    try:
        layout = json.loads((found["meta"] or b"{}").decode("utf-8", "ignore")) or {}
    except ValueError:
        layout = {}
    out, used = [], set()
    for tag, items in (layout.items() if isinstance(layout, dict) else []):
        for item in items if isinstance(items, list) else []:
            index = item.get("index") if isinstance(item, dict) else None
            if isinstance(index, int) and 0 <= index < len(images) and index not in used:
                used.add(index)
                out.append((tag, item.get("filename") or f"{tag}.png", index))
    out += [("image_refs", f"embedded_{i + 1}.png", i) for i in range(len(images)) if i not in used]
    result = []
    for tag, filename, index in out:
        offset, length, type_code = images[index]
        mime = "image/png" if type_code == 14 else "image/jpeg"
        result.append((tag, filename, offset, length, mime))
    return result


def embedded_images(entry):
    if not str(entry.get("path", "")).lower().endswith((".mp4", ".m4v", ".mov")):
        return []
    key = f"{entry['path']}|{entry.get('size')}|{entry.get('mtime')}"
    with _embed_lock:
        if key in _embed_cache:
            return _embed_cache[key]
    value = _embedded_index(entry["path"])
    with _embed_lock:
        _embed_cache[key] = value
    return value


# -- the resolver ------------------------------------------------------------

def collect(entry):
    """Every input reference a clip records, with an `n` usable in /input/<id>/<n>."""
    meta = entry.get("meta") or {}
    refs = []

    def add(key, raw, resolved, **extra):
        label = LABELS.get(key, key.replace("_", " ").capitalize())
        refs.append(dict({
            "n": len(refs), "key": key, "label": label, "recorded": raw,
            "name": Path(str(raw)).name, "kind": kind_of(raw),
            "exists": resolved is not None, "_path": str(resolved) if resolved else None,
        }, **extra))

    for key in WANGP_KEYS:
        for raw in _strings(meta.get(key)):
            add(key, raw, _resolve(raw, entry), source="path")

    prompt = (meta.get("_comfy") or {}).get("prompt") if isinstance(meta.get("_comfy"), dict) else None
    if isinstance(prompt, dict):
        root = Path(entry.get("root") or Path(entry["path"]).parent)
        comfy_dirs = (root.parent / "input", root / "input")
        for node_id in sorted(prompt, key=lambda k: (len(str(k)), str(k))):
            node = prompt[node_id]
            if not isinstance(node, dict) or node.get("class_type") not in COMFY_LOADERS:
                continue
            inputs = node.get("inputs") or {}
            for field in ("image", "video", "file", "path"):
                raw = inputs.get(field)
                if isinstance(raw, str) and raw.strip():
                    clean = raw.rsplit(" [", 1)[0]  # "name.png [input]" annotation
                    kind = COMFY_LOADERS[node["class_type"]]
                    add(f"comfy_{kind}", clean, _resolve(clean, entry, comfy_dirs), source="path", node=str(node_id))
                    break

    for tag, filename, offset, length, mime in embedded_images(entry):
        add(tag, filename, entry["path"], source="embedded", _range=(offset, length), _mime=mime)
        refs[-1]["kind"] = "image"
        refs[-1]["recorded"] = f"embedded in {Path(entry['path']).name}"
    return refs


def public(refs):
    return [{k: v for k, v in ref.items() if not k.startswith("_")} for ref in refs]


def lookup(entry, n_text):
    """Return the allow-listed ref for `n_text`, or None (unknown, missing, malformed)."""
    if not entry or not str(n_text).isdigit():
        return None
    n = int(n_text)
    refs = collect(entry)
    if n >= len(refs) or not refs[n]["exists"]:
        return None
    return refs[n]


def read_embedded(ref):
    offset, length = ref["_range"]
    with open(ref["_path"], "rb") as handle:
        handle.seek(offset)
        return handle.read(length)
