"""
Generation-metadata reading and normalisation for WanGP Video Browser.

Standard library only. Reads the text tags a video container carries (MP4/MOV
`ilst` / QuickTime `udta` items, Matroska/WebM `Tags`, or ffprobe as a fallback)
and turns whatever generator wrote them into the flat settings dict the UI
already understands (WanGP's own keys):

    seed, num_inference_steps, guidance_scale, sample_solver, resolution,
    prompt, negative_prompt, activated_loras, loras_multipliers, model_type

`meta["_source"]` records where the settings came from ("wangp", "comfyui",
"unknown", ...). Files without any metadata still yield `{}`.
"""

import json
import os
import re
import subprocess

# Bump whenever normalisation changes so cached index entries are rebuilt.
META_VERSION = 2

RESERVED_METADATA_KEY = "_wangp_metadata_reserved"

# Keys tried first, in order, when looking for a settings payload.
PRIORITY_TAGS = ("comment", "description", "parameters", "prompt", "workflow", "synopsis")

MP4_TAG_NAMES = {
    b"\xa9cmt": "comment", b"\xa9des": "description", b"desc": "description",
    b"ldes": "synopsis", b"\xa9nam": "title", b"\xa9too": "encoder", b"\xa9inf": "information",
}


# ---------------------------------------------------------------------------
# Container readers
# ---------------------------------------------------------------------------

def _iter_boxes(handle, start, end):
    pos = start
    while pos + 8 <= end:
        handle.seek(pos)
        header = handle.read(8)
        if len(header) < 8:
            return
        size = int.from_bytes(header[0:4], "big")
        box_type = header[4:8]
        body = pos + 8
        if size == 1:
            extended = handle.read(8)
            if len(extended) < 8:
                return
            size = int.from_bytes(extended, "big")
            body = pos + 16
        elif size == 0:
            size = end - pos
        if size < 8 or pos + size > end:
            return
        yield box_type, body, pos + size
        pos += size


def _read(handle, start, end, limit=64 * 1024 * 1024):
    handle.seek(start)
    return handle.read(max(0, min(end - start, limit)))


def _decode(raw):
    return raw.decode("utf-8", errors="ignore").replace("\ufeff", "").strip("\0").strip()


def _ilst_value(handle, body, end):
    """Return (freeform_name, text) for one ilst item."""
    name, text = None, None
    for inner, ibody, iend in _iter_boxes(handle, body, end):
        if inner == b"name":
            name = _decode(_read(handle, ibody + 4, iend))
        elif inner == b"data" and text is None:
            text = _decode(_read(handle, ibody + 8, iend))
    return name, text


def _mp4_tags(handle, start, end, tags, depth=0):
    if depth > 6:
        return
    for box_type, body, box_end in _iter_boxes(handle, start, end):
        if box_type in (b"moov", b"udta", b"trak"):
            _mp4_tags(handle, body, box_end, tags, depth + 1)
        elif box_type == b"meta":
            _mp4_meta(handle, body, box_end, tags, depth)
        elif depth and (box_type[:1] == b"\xa9" or box_type in MP4_TAG_NAMES):
            # QuickTime-style udta text item: [len:2][lang:2][text] (or ilst-like data child).
            name = MP4_TAG_NAMES.get(box_type) or box_type[1:].decode("latin-1", "ignore")
            _, text = _ilst_value(handle, body, box_end)
            if text is None:
                raw = _read(handle, body, box_end)
                length = int.from_bytes(raw[0:2], "big") if len(raw) >= 4 else 0
                text = _decode(raw[4:4 + length] if 0 < length <= len(raw) - 4 else raw[4:])
            if text:
                tags.setdefault(name, text)


def _mp4_meta(handle, body, end, tags, depth):
    # `meta` is a FullBox in MP4 but not in QuickTime; detect by peeking for hdlr.
    handle.seek(body + 4)
    start = body if handle.read(4) == b"hdlr" else body + 4
    keys = []
    for box_type, ibody, iend in _iter_boxes(handle, start, end):
        if box_type == b"keys":
            raw = _read(handle, ibody, iend)
            count, pos = int.from_bytes(raw[4:8], "big"), 8
            for _ in range(count):
                size = int.from_bytes(raw[pos:pos + 4], "big")
                if size < 8:
                    break
                key = raw[pos + 8:pos + size].decode("utf-8", "ignore")
                keys.append(key.rsplit(".", 1)[-1])
                pos += size
        elif box_type == b"ilst":
            for item, item_body, item_end in _iter_boxes(handle, ibody, iend):
                name, text = _ilst_value(handle, item_body, item_end)
                index = int.from_bytes(item, "big")
                if item == b"----":
                    key = name
                elif keys and 1 <= index <= len(keys):
                    key = keys[index - 1]
                else:
                    key = MP4_TAG_NAMES.get(item) or item.decode("latin-1", "ignore").lstrip("\xa9")
                if key and text:
                    tags.setdefault(key.lower(), text)


def read_mp4_tags(path):
    tags = {}
    try:
        with open(path, "rb") as handle:
            _mp4_tags(handle, 0, os.path.getsize(path), tags)
    except OSError:
        return {}
    return tags


# Matroska / WebM (EBML)
_EBML_SEGMENT, _EBML_TAGS, _EBML_TAG, _EBML_SIMPLETAG = 0x18538067, 0x1254C367, 0x7373, 0x67C8
_EBML_TAGNAME, _EBML_TAGSTRING = 0x45A3, 0x4487


def _ebml_vint(handle, keep_marker):
    first = handle.read(1)
    if not first:
        return None, 0
    byte = first[0]
    length = 1
    while length <= 8 and not byte & (0x80 >> (length - 1)):
        length += 1
    if length > 8:
        return None, 0
    rest = handle.read(length - 1)
    value = byte if keep_marker else byte & (0xFF >> length)
    for b in rest:
        value = (value << 8) | b
    unknown = not keep_marker and value == (1 << (7 * length)) - 1
    return (None if unknown else value), length


def _ebml_children(handle, start, end, max_items=200000):
    pos = start
    for _ in range(max_items):
        if pos >= end:
            return
        handle.seek(pos)
        element_id, id_len = _ebml_vint(handle, True)
        size, size_len = _ebml_vint(handle, False)
        if element_id is None or not id_len or not size_len:
            return
        body = pos + id_len + size_len
        if size is None:  # unknown size: only meaningful for the segment itself
            yield element_id, body, end
            return
        yield element_id, body, body + size
        pos = body + size


def read_mkv_tags(path):
    tags = {}
    try:
        total = os.path.getsize(path)
        with open(path, "rb") as handle:
            for element_id, body, end in _ebml_children(handle, 0, total):
                if element_id != _EBML_SEGMENT:
                    continue
                for child_id, cbody, cend in _ebml_children(handle, body, min(end, total)):
                    if child_id != _EBML_TAGS:
                        continue
                    for tag_id, tbody, tend in _ebml_children(handle, cbody, cend):
                        if tag_id != _EBML_TAG:
                            continue
                        for simple_id, sbody, send in _ebml_children(handle, tbody, tend):
                            if simple_id != _EBML_SIMPLETAG:
                                continue
                            name = text = None
                            for field_id, fbody, fend in _ebml_children(handle, sbody, send):
                                if field_id == _EBML_TAGNAME:
                                    name = _decode(_read(handle, fbody, fend))
                                elif field_id == _EBML_TAGSTRING:
                                    text = _decode(_read(handle, fbody, fend))
                            if name and text:
                                tags.setdefault(name.lower(), text)
    except OSError:
        return {}
    return tags


def read_ffprobe_tags(path, ffprobe):
    if not ffprobe:
        return {}
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=30, check=False,
        )
        tags = ((json.loads(result.stdout or "{}") or {}).get("format") or {}).get("tags") or {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}
    return {str(k).lower(): str(v) for k, v in tags.items() if v}


def read_tags(path, ffprobe=None):
    lower = str(path).lower()
    tags = {}
    if lower.endswith((".mp4", ".mov", ".m4v")):
        tags = read_mp4_tags(path)
    elif lower.endswith((".mkv", ".webm")):
        tags = read_mkv_tags(path)
    if not any(k in tags for k in PRIORITY_TAGS):
        for key, value in read_ffprobe_tags(path, ffprobe).items():
            tags.setdefault(key, value)
    return tags


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _json(text):
    if isinstance(text, (dict, list)):
        return text
    try:
        return json.loads(str(text or "").replace("\ufeff", "").strip("\0").strip())
    except (TypeError, ValueError):
        return None


def _is_api_graph(value):
    return isinstance(value, dict) and value and all(
        isinstance(node, dict) and "class_type" in node for node in value.values())


def _is_ui_workflow(value):
    return isinstance(value, dict) and isinstance(value.get("nodes"), list)


def _base(name):
    return str(name).replace("\\", "/").rsplit("/", 1)[-1]


def _strip_ext(name):
    base = _base(name)
    for ext in (".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin", ".sft"):
        if base.lower().endswith(ext):
            return base[: -len(ext)]
    return base


def _num(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value) if abs(value) < 1e15 else value
    return value


SAMPLER_TYPES = ("KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced",
                 "WanVideoSampler", "HyVideoSampler", "LTXVSampler")
MODEL_LOADERS = {
    "CheckpointLoaderSimple": "ckpt_name", "CheckpointLoader": "ckpt_name", "UNETLoader": "unet_name",
    "UnetLoaderGGUF": "unet_name", "UnetLoaderGGUFAdvanced": "unet_name", "WanVideoModelLoader": "model",
    "HyVideoModelLoader": "model", "DownloadAndLoadWanVideoModel": "model", "LTXVLoader": "ckpt_name",
    "ImageOnlyCheckpointLoader": "ckpt_name", "DiffusionModelLoaderKJ": "model_name",
}
LATENT_SIZE_KEYS = (("width", "height"),)
FRAME_KEYS = ("length", "num_frames", "video_length", "frames", "frame_count")


class _Graph:
    """Resolve values through ComfyUI API-format links (`[node_id, slot]`)."""

    def __init__(self, nodes):
        self.nodes = {str(k): v for k, v in nodes.items()}

    @staticmethod
    def is_link(value):
        return isinstance(value, list) and len(value) == 2 and isinstance(value[1], int) \
            and isinstance(value[0], (str, int))

    def node(self, link):
        return self.nodes.get(str(link[0])) if self.is_link(link) else None

    def inputs(self, node):
        return (node or {}).get("inputs") or {}

    def value(self, node, key, depth=0):
        """Literal value of an input, following links into primitive/string nodes."""
        raw = self.inputs(node).get(key)
        if not self.is_link(raw):
            return raw
        if depth > 8:
            return None
        target = self.node(raw)
        if not target:
            return None
        tinputs = self.inputs(target)
        for candidate in (key, "value", "string", "text", "seed", "noise_seed", "int", "float", "number"):
            if candidate in tinputs:
                return self.value(target, candidate, depth + 1)
        literals = [k for k, v in tinputs.items() if isinstance(v, (str, int, float)) and not isinstance(v, bool)]
        return self.value(target, literals[0], depth + 1) if len(literals) == 1 else None

    def text(self, link, depth=0):
        """Prompt text behind a conditioning link (CLIPTextEncode and friends)."""
        node = self.node(link)
        if not node or depth > 8:
            return None
        inputs = self.inputs(node)
        for key in ("text", "positive_prompt", "prompt", "text_g", "string", "value"):
            if key in inputs:
                value = self.value(node, key)
                if isinstance(value, str):
                    return value
        for key in ("conditioning", "positive", "conditioning_to", "conditioning_1"):
            if self.is_link(inputs.get(key)):
                found = self.text(inputs[key], depth + 1)
                if found is not None:
                    return found
        return None

    def upstream(self, link, follow=("model", "lora", "prev_lora", "unet", "diffusion_model"), limit=40):
        seen, out, frontier = set(), [], [link]
        while frontier and len(out) < limit:
            current = frontier.pop(0)
            if not self.is_link(current) or str(current[0]) in seen:
                continue
            seen.add(str(current[0]))
            node = self.node(current)
            if not node:
                continue
            out.append(node)
            for key in follow:
                if self.is_link(self.inputs(node).get(key)):
                    frontier.append(self.inputs(node)[key])
        return out


def _comfy_from_api(nodes):
    graph = _Graph(nodes)
    samplers = sorted(
        ((k, v) for k, v in graph.nodes.items() if v.get("class_type") in SAMPLER_TYPES),
        key=lambda kv: (0, int(kv[0])) if str(kv[0]).isdigit() else (1, str(kv[0])),
    )
    meta = {}
    if not samplers:
        return meta
    sampler = samplers[0][1]
    inputs = graph.inputs(sampler)
    get = lambda key, node=sampler: graph.value(node, key)  # noqa: E731

    # Pieces SamplerCustom(Advanced) spreads over helper nodes.
    guider = graph.node(inputs.get("guider"))
    sigmas = graph.node(inputs.get("sigmas"))
    sampler_select = graph.node(inputs.get("sampler"))
    noise = graph.node(inputs.get("noise"))

    seed = next((v for v in (get("seed"), get("noise_seed"),
                             graph.value(noise, "noise_seed") if noise else None) if v is not None), None)
    steps = get("steps")
    if steps is None and sigmas:
        steps = graph.value(sigmas, "steps")
    cfg = next((v for v in (get("cfg"), graph.value(guider, "cfg") if guider else None) if v is not None), None)
    solver = get("sampler_name")
    if solver is None and sampler_select:
        solver = graph.value(sampler_select, "sampler_name")
    scheduler = get("scheduler")
    if scheduler is None and sigmas:
        scheduler = graph.value(sigmas, "scheduler")
    if solver is None and sampler.get("class_type", "").startswith(("WanVideo", "HyVideo")):
        solver = scheduler  # wrapper samplers name the solver "scheduler" (unipc, euler, dpm++)

    cond_owner = guider if guider else sampler
    positive = graph.text(graph.inputs(cond_owner).get("positive"))
    negative = graph.text(graph.inputs(cond_owner).get("negative"))
    embeds = graph.node(inputs.get("text_embeds") or inputs.get("hyvid_embeds"))
    if embeds:  # WanVideo / HyVideo wrapper text encoders
        positive = positive or graph.value(embeds, "positive_prompt") or graph.value(embeds, "prompt")
        negative = negative or graph.value(embeds, "negative_prompt")
    if positive is None and guider:
        positive = graph.text(graph.inputs(guider).get("conditioning"))

    model_link = inputs.get("model") or graph.inputs(guider).get("model")
    loras, model_name, shift = [], None, get("shift")
    for node in graph.upstream(model_link):
        ctype = node.get("class_type", "")
        if "lora" in ctype.lower():
            name = graph.value(node, "lora_name") or graph.value(node, "lora")
            if isinstance(name, str) and name.lower() not in ("none", ""):
                strength = graph.value(node, "strength_model")
                if strength is None:
                    strength = graph.value(node, "strength")
                loras.append((name, strength))
        if model_name is None and ctype in MODEL_LOADERS:
            model_name = graph.value(node, MODEL_LOADERS[ctype])
        if shift is None and ctype.startswith("ModelSampling") and graph.value(node, "shift") is not None:
            shift = graph.value(node, "shift")
    if model_name is None:  # fall back to any loader in the graph
        for node in graph.nodes.values():
            key = MODEL_LOADERS.get(node.get("class_type"))
            if key and isinstance(graph.value(node, key), str):
                model_name = graph.value(node, key)
                break
    loras.reverse()  # loader-closest first = the order they are applied

    width = height = frames = None
    latent = graph.node(inputs.get("latent_image") or inputs.get("image_embeds") or inputs.get("latent"))
    candidates = ([latent] if latent else []) + list(graph.nodes.values())
    for node in candidates:
        w, h = graph.value(node, "width"), graph.value(node, "height")
        if isinstance(w, (int, float)) and isinstance(h, (int, float)):
            width, height = int(w), int(h)
            frames = next((graph.value(node, k) for k in FRAME_KEYS if graph.value(node, k) is not None), None)
            break

    meta.update({
        "seed": _num(seed),
        "num_inference_steps": _num(steps),
        "guidance_scale": _num(cfg),
        "sample_solver": solver,
        "scheduler": scheduler,
        "denoise": _num(get("denoise")),
        "flow_shift": _num(shift),
        "prompt": positive,
        "negative_prompt": negative,
        "resolution": f"{width}x{height}" if width and height else None,
        "video_length": _num(frames),
        "model_type": _strip_ext(model_name) if isinstance(model_name, str) else None,
        "model_filename": model_name if isinstance(model_name, str) else None,
        "activated_loras": [_base(name) for name, _ in loras],
        "loras_multipliers": " ".join(str(_num(s) if s is not None else 1) for _, s in loras),
        "comfy_sampler": sampler.get("class_type"),
    })
    return meta


# Positional widget layouts for the UI-format workflow (used when no API prompt is embedded).
UI_WIDGETS = {
    "KSampler": ("seed", None, "steps", "cfg", "sampler_name", "scheduler", "denoise"),
    "KSamplerAdvanced": (None, "seed", None, "steps", "cfg", "sampler_name", "scheduler"),
    "CLIPTextEncode": ("text",),
    "LoraLoader": ("lora_name", "strength_model", "strength_clip"),
    "LoraLoaderModelOnly": ("lora_name", "strength_model"),
    "CheckpointLoaderSimple": ("ckpt_name",),
    "UNETLoader": ("unet_name", "weight_dtype"),
    "EmptyLatentImage": ("width", "height", "batch_size"),
    "EmptyHunyuanLatentVideo": ("width", "height", "length", "batch_size"),
    "EmptySD3LatentImage": ("width", "height", "batch_size"),
}


def _api_from_ui(workflow):
    """Rebuild an approximate API graph from a UI workflow (nodes + links)."""
    links = {}
    for link in workflow.get("links") or []:
        if isinstance(link, list) and len(link) >= 4:
            links[link[0]] = [str(link[1]), int(link[2])]
    nodes = {}
    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict) or "id" not in node:
            continue
        inputs = {}
        layout = UI_WIDGETS.get(node.get("type"), ())
        widgets = node.get("widgets_values")
        if isinstance(widgets, list):
            for name, value in zip(layout, widgets):
                if name:
                    inputs[name] = value
        elif isinstance(widgets, dict):
            inputs.update(widgets)
        for slot in node.get("inputs") or []:
            if isinstance(slot, dict) and slot.get("link") in links:
                inputs[slot.get("name")] = links[slot["link"]]
        nodes[str(node["id"])] = {"class_type": node.get("type"), "inputs": inputs}
    return nodes


def comfy_meta(prompt, workflow):
    api = prompt if _is_api_graph(prompt) else None
    if api is None and _is_ui_workflow(workflow):
        api = _api_from_ui(workflow)
    meta = _comfy_from_api(api) if api else {}
    meta = {k: v for k, v in meta.items() if v not in (None, "")}
    meta["_source"] = "comfyui"
    meta["_comfy"] = {"prompt": prompt if _is_api_graph(prompt) else None,
                      "workflow": workflow if _is_ui_workflow(workflow) else None}
    return meta


def _looks_wangp(meta):
    return str(meta.get("type", "")).lstrip().lower().startswith("wangp") or \
        "settings_version" in meta or "base_model_type" in meta or "model_type" in meta


# ---------------------------------------------------------------------------
# A1111 / Forge `parameters` text, LTX-Video / HunyuanVideo argument JSON
# ---------------------------------------------------------------------------

A1111_PARAM_RE = re.compile(r'\s*([\w ./+-]+):\s*("(?:\\.|[^\\"])+"|[^,]*)(?:,|$)')
A1111_LORA_RE = re.compile(r"<lora:([^:>]+)(?::([-\d.]+))?[^>]*>")
A1111_KEYS = {
    "steps": "num_inference_steps", "sampler": "sample_solver", "schedule type": "scheduler",
    "cfg scale": "guidance_scale", "distilled cfg scale": "embedded_guidance_scale", "seed": "seed",
    "size": "resolution", "model": "model_type", "model hash": "model_hash",
    "denoising strength": "denoise", "shift": "flow_shift", "version": "version",
    "frames": "video_length", "fps": "fps",
}


def _scalar(text):
    text = str(text).strip()
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        try:
            return json.loads(text)
        except ValueError:
            return text[1:-1]
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d*\.\d+(?:e-?\d+)?", text):
        return _num(float(text))
    return text


def parse_a1111(text):
    """`parameters` text as written by A1111 / Forge / SD.Next. None if it is not one."""
    lines = str(text or "").strip().replace("\r\n", "\n").split("\n")
    index = next((i for i in range(len(lines) - 1, -1, -1) if re.match(r"\s*Steps:\s*\d", lines[i])), None)
    if index is None:
        return None
    body, negative, in_negative = [], [], False
    for line in lines[:index]:
        if line.startswith("Negative prompt:"):
            in_negative, line = True, line[len("Negative prompt:"):].lstrip()
        (negative if in_negative else body).append(line)
    meta = {"prompt": "\n".join(body).strip(), "negative_prompt": "\n".join(negative).strip()}
    for key, value in A1111_PARAM_RE.findall(" ".join(lines[index:])):
        key = key.strip()
        target = A1111_KEYS.get(key.lower()) or re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
        if target:
            meta[target] = _scalar(value)
    if isinstance(meta.get("resolution"), str):
        meta["resolution"] = meta["resolution"].replace(" ", "")
    loras = A1111_LORA_RE.findall(meta["prompt"])
    meta["activated_loras"] = [name for name, _ in loras]
    meta["loras_multipliers"] = " ".join(weight or "1" for _, weight in loras)
    version = str(meta.get("version", ""))
    meta["_source"] = "forge" if re.match(r"f\d", version) else \
        "sdnext" if "sd.next" in str(meta.get("app", "")).lower() else "a1111"
    return {k: v for k, v in meta.items() if v not in (None, "")} | {"_source": meta["_source"]}


GENERIC_ALIASES = {
    "prompt": ("prompt", "positive_prompt"),
    "negative_prompt": ("negative_prompt", "neg_prompt", "negative"),
    "seed": ("seed", "seeds"),
    "num_inference_steps": ("num_inference_steps", "infer_steps", "steps"),
    "guidance_scale": ("guidance_scale", "cfg_scale", "cfg"),
    "flow_shift": ("flow_shift", "shift"),
    "sample_solver": ("sample_solver", "sampler", "flow_solver", "scheduler"),
    "video_length": ("video_length", "num_frames", "frames"),
    "model_type": ("model_type", "model", "dit_weight", "ckpt_path", "model_path", "pipeline_config"),
}
LTX_HINTS = {"stg_scale", "stg_mode", "stg_skip_layers", "pipeline_config", "conditioning_media_paths",
             "conditioning_start_frames", "image_cond_noise_scale"}
HUNYUAN_HINTS = {"infer_steps", "embedded_guidance_scale", "video_size", "dit_weight", "flow_reverse",
                 "neg_prompt", "i2v_mode", "use_cpu_offload"}


def _generator_of(meta):
    keys = set(meta)
    blob = " ".join(str(meta.get(k, "")) for k in ("model", "model_type", "dit_weight", "ckpt_path",
                                                    "model_path", "pipeline_config", "generator", "type")).lower()
    if keys & LTX_HINTS or "ltx" in blob:
        return "ltx-video"
    if keys & HUNYUAN_HINTS or "hunyuan" in blob:
        return "hunyuan"
    return None


def normalise_generic(parsed, source):
    meta = dict(parsed)
    for target, aliases in GENERIC_ALIASES.items():
        for alias in aliases:
            if alias in meta and not isinstance(meta[alias], (dict,)):
                value = meta.pop(alias)
                if target not in meta:
                    meta[target] = value
                break
    seed = meta.get("seed")
    if isinstance(seed, list):
        meta["seed"] = seed[0] if seed else None
    if isinstance(meta.get("model_type"), str):
        meta["model_type"] = _strip_ext(meta["model_type"])
    if "resolution" not in meta:
        size = meta.pop("video_size", None)
        width, height = meta.get("width"), meta.get("height")
        if isinstance(size, (list, tuple)) and len(size) == 2:  # Hunyuan: [height, width]
            height, width = size
        if width and height:
            meta["resolution"] = f"{int(width)}x{int(height)}"
            meta.pop("width", None)
            meta.pop("height", None)
    for key in ("guidance_scale", "flow_shift", "num_inference_steps", "seed"):
        if isinstance(meta.get(key), float):
            meta[key] = _num(meta[key])
    meta = {k: v for k, v in meta.items() if v is not None}
    meta["_source"] = source
    return meta


def normalise_tags(tags):
    """Turn raw container tags into the UI's settings dict ({} when nothing usable)."""
    ordered = [k for k in PRIORITY_TAGS if k in tags] + [k for k in tags if k not in PRIORITY_TAGS]

    # ComfyUI writers may also store `prompt` / `workflow` as separate tags.
    sep_prompt, sep_workflow = _json(tags.get("prompt")), _json(tags.get("workflow"))
    if _is_api_graph(sep_prompt) or _is_ui_workflow(sep_workflow):
        return comfy_meta(sep_prompt, sep_workflow)

    for key in ordered:
        parsed = _json(tags[key])
        if not isinstance(parsed, dict):
            continue
        if parsed.get(RESERVED_METADATA_KEY):
            return {}
        prompt, workflow = _json(parsed.get("prompt")), _json(parsed.get("workflow"))
        if _is_api_graph(prompt) or _is_ui_workflow(workflow):
            return comfy_meta(prompt, workflow)
        if _is_api_graph(parsed):
            return comfy_meta(parsed, None)
        if _is_ui_workflow(parsed):
            return comfy_meta(None, parsed)
        if _looks_wangp(parsed):
            return dict(parsed, _source="wangp")
        generator = _generator_of(parsed)
        if generator:
            return normalise_generic(parsed, generator)
        return dict(parsed, _source="unknown")
    for key in ordered:
        meta = parse_a1111(tags[key])
        if meta:
            return meta
    return {}


def read_video_metadata(path, ffprobe=None):
    return normalise_tags(read_tags(path, ffprobe))
