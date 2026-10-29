"use strict";

/* ==========================================================================
   WanGP Video Browser
   ========================================================================== */

/* ------------------------------------------------------------------ state */
const state = {
  facets: {},           // library filters: { model, steps, res, lora }
  videos: [],
  roots: [],
  ffmpeg: false,
  activeId: null,
  picks: [],            // ids (or local:* ids) in compare order, max 4
  external: new Map(),  // id -> {id, name, url, meta, probe, external:true}
  view: "preview",
  sheet: false,         // mobile only: is the preview sheet open
  loop: true,
  unmuted: null,        // index of the clip allowed to make noise
  rate: 1,
  cmpMode: "side",      // side | wipe | blink
  modeTouched: false,   // has the user chosen a mode this session
  wipe: 50,             // wipe divider position, percent
  blinkMs: 0,           // 0 = manual swap only
  blinkFlip: false,     // which clip the blink stack is currently showing
  diffAll: false,       // show unchanged settings too
  showBlank: false,     // preview: list settings WanGP left empty
};

const MAX_PICKS = 4;

/* WanGP settings, grouped for display. Anything unknown lands in "Other". */
const GROUPS = [
  ["Model", ["type", "model_type", "model_filename", "settings_version"]],
  ["Generation", ["seed", "resolution", "video_length", "batch_size", "num_inference_steps",
    "guidance_scale", "guidance2_scale", "guidance3_scale", "embedded_guidance_scale", "guidance_phases",
    "audio_guidance_scale", "flow_shift", "sample_solver", "NAG_scale", "NAG_tau", "NAG_alpha",
    "repeat_generation", "multi_prompts_gen_type", "RIFLEx_setting", "denoising_strength"]],
  ["Speed / cache", ["skip_steps_cache_type", "skip_steps_multiplier", "skip_steps_start_step_perc",
    "override_profile", "override_attention"]],
  ["LoRAs", ["activated_loras", "loras_multipliers"]],
  ["Sliding window", ["sliding_window_size", "sliding_window_overlap", "sliding_window_color_correction_strength",
    "sliding_window_overlap_noise", "sliding_window_discard_last_frames", "sliding_window_trim_first_frames"]],
  ["Prompt / inputs", ["prompt", "alt_prompt", "negative_prompt", "image_prompt_type", "video_prompt_type",
    "audio_prompt_type", "keep_frames_video_guide", "mask_expand", "replace_voice_method", "image_refs_relative_size"]],
  ["Post-processing", ["temporal_upsampling", "spatial_upsampling", "film_grain_intensity", "film_grain_saturation",
    "postprocess_audio", "video_quality"]],
  ["Output", ["output_filename", "config", "client_id", "image_mode", "generation_time",
    "creation_date", "creation_timestamp"]],
];
const GROUPED_KEYS = new Set(GROUPS.flatMap(([, keys]) => keys));
/* Redundant with a friendlier key ("Created"), so never listed. */
const HIDDEN_KEYS = new Set(["creation_timestamp"]);

/* Human labels for WanGP's snake_case keys. The raw key stays available as a
   tooltip, so nothing is hidden from people who know the settings file. */
const LABELS = {
  type: "Model", model_type: "Model id", base_model_type: "Base model", model_filename: "Weights",
  settings_version: "Settings version", modules: "Modules",
  seed: "Seed", resolution: "Resolution", video_length: "Frames", batch_size: "Batch size",
  num_inference_steps: "Steps", guidance_scale: "Guidance", guidance2_scale: "Guidance 2",
  guidance3_scale: "Guidance 3", embedded_guidance_scale: "Embedded guidance", guidance_phases: "Guidance phases",
  audio_guidance_scale: "Audio guidance", flow_shift: "Flow shift", sample_solver: "Solver",
  NAG_scale: "NAG scale", NAG_tau: "NAG tau", NAG_alpha: "NAG alpha", repeat_generation: "Repeats",
  multi_prompts_gen_type: "Multi-prompt mode", RIFLEx_setting: "RIFLEx", denoising_strength: "Denoise strength",
  force_fps: "Forced FPS", input_video_strength: "Input video strength",
  skip_steps_cache_type: "Step cache", skip_steps_multiplier: "Cache multiplier",
  skip_steps_start_step_perc: "Cache start", override_profile: "Memory profile", override_attention: "Attention",
  activated_loras: "LoRAs", loras_multipliers: "LoRA weights",
  sliding_window_size: "Window size", sliding_window_overlap: "Window overlap",
  sliding_window_color_correction_strength: "Colour correction", sliding_window_overlap_noise: "Overlap noise",
  sliding_window_discard_last_frames: "Discard last frames", sliding_window_trim_first_frames: "Trim first frames",
  prompt: "Prompt", alt_prompt: "Alt prompt", negative_prompt: "Negative prompt",
  image_prompt_type: "Image prompt", video_prompt_type: "Video prompt", audio_prompt_type: "Audio prompt",
  keep_frames_video_guide: "Keep guide frames", mask_expand: "Mask expand", replace_voice_method: "Voice replace",
  image_refs_relative_size: "Reference size", remove_background_images_ref: "Remove reference background",
  temporal_upsampling: "Temporal upsampling", spatial_upsampling: "Spatial upsampling",
  spatial_upsampler_prompt: "Upsampler prompt", spatial_upsampler_reference_images: "Upsampler references",
  spatial_upsampler_param: "Upsampler param", spatial_upsampler_param2: "Upsampler param 2",
  spatial_upsampler_parameters: "Upsampler settings", film_grain_intensity: "Film grain",
  film_grain_saturation: "Grain saturation", postprocess_audio: "Audio post-process", video_quality: "Encoder",
  output_filename: "Output name", config: "Config", client_id: "Client", image_mode: "Image mode",
  generation_time: "Generation time", creation_date: "Created", creation_timestamp: "Timestamp",
  overrides: "Overrides", custom_settings: "Custom settings", output_role: "Output role", num_inference_steps2: "Steps (phase 2)",
};
const labelOf = (key) => LABELS[key] || key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

/* WanGP writes "nothing" many ways; none of them are worth a row. */
const isBlank = (value) => value === null || value === undefined ||
  (Array.isArray(value) && !value.length) ||
  (typeof value === "object" && !Array.isArray(value) && !Object.keys(value).length) ||
  ["", "[]", "{}", "None", "none", "null"].includes(String(value).trim());

/* Some values arrive as Python reprs ("{'a': 1, 'b': True}"). Read them as data
   when that is safe, so they can be laid out instead of shown as one blob. */
const parseLoose = (value) => {
  if (typeof value !== "string") return value;
  const text = value.trim();
  if (!/^[[{]/.test(text)) return value;
  try { return JSON.parse(text); } catch (e) { /* fall through */ }
  try {
    return JSON.parse(text.replace(/'/g, "\"").replace(/\bTrue\b/g, "true")
      .replace(/\bFalse\b/g, "false").replace(/\bNone\b/g, "null"));
  } catch (e) { return value; }
};

const fmtSpan = (seconds) => {
  const s = Math.round(Number(seconds));
  if (!isFinite(s) || s <= 0) return null;
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h} h ${m} min` : m ? `${m} min ${r} s` : `${r} s`;
};
/* "WanGP v18.84 by DeepBeepMeep - MiniMax H3 Ref2VA 20B" -> "MiniMax H3 Ref2VA 20B" */
const modelName = (meta) => {
  const raw = String(meta.type || "").replace(/^\s*WanGP\s+v[\d.]+\s+by\s+\S+\s*-\s*/i, "").trim();
  return raw || meta.model_type || meta.base_model_type || "Unknown model";
};
const fileBase = (path) => String(path || "").split(/[\\/]/).pop();

/* The one rendering of a setting value, shared by the preview and the diff. */
function displayValue(key, raw, video) {
  const value = parseLoose(raw);
  if (isBlank(value)) return "—";
  const fps = video ? fpsOf(video) : 16;
  switch (key) {
    case "video_length": {
      const n = Number(value);
      return isFinite(n) && n > 0 ? `${n} · ${(n / fps).toFixed(1)} s` : String(value);
    }
    case "generation_time": return fmtSpan(value) || String(value);
    case "creation_date": {
      const d = new Date(value);
      return isNaN(d) ? String(value) : d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
    }
    case "model_filename": return fileBase(value);
    case "type": return modelName({ type: value });
    case "resolution": return String(value).replace("x", " × ");
    default: break;
  }
  if (Array.isArray(value)) {
    return value.map((item) => (Array.isArray(item) ? item.map(fileBase).join(" ") : fileBase(item))).join(", ");
  }
  if (typeof value === "object") {
    return Object.entries(value).filter(([, v]) => !isBlank(v))
      .map(([k, v]) => `${k.replace(/_/g, " ")}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join("\n") || "—";
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

/* WanGP's placeholders (<Subject 1>, [Shot 2]) are references, not words -
   set them as quiet tokens so the sentence around them reads normally. */
const TOKEN_RE = /<((?:Subject|Picture|Image|Video|Audio)\s*\d+)>|\[((?:Shot|Scene)\s*\d+)\]/g;
function placeholders(text) {
  const out = [];
  let last = 0;
  for (const m of String(text).matchAll(TOKEN_RE)) {
    if (m.index > last) out.push(String(text).slice(last, m.index));
    out.push(el("span", { className: "tok" }, m[1] || m[2]));
    last = m.index + m[0].length;
  }
  out.push(String(text).slice(last));
  return out;
}

/* LoRAs and their weights live in two parallel fields; read them as one list. */
function loraList(meta) {
  const names = parseLoose(meta.activated_loras);
  const list = Array.isArray(names) ? names : isBlank(names) ? [] : String(names).split(/[,\n]/);
  const weights = String(meta.loras_multipliers || "").trim().split(/\s+/).filter(Boolean);
  return list.map((name, i) => ({
    name: fileBase(String(name).trim()).replace(/\.safetensors$/i, ""),
    weight: weights[i] || null,
  })).filter((lora) => lora.name);
}

/* ---------------------------------------------------------------- helpers */
const $ = (sel, root = document) => root.querySelector(sel);
/* `ariaLabel` -> `aria-label` explicitly. Going through the DOM property would
   rely on ARIA reflection, and on a browser without it the fallback would
   silently write a meaningless ` arialabel` attribute instead of failing. */
const ariaAttr = (key) => key.replace(/^aria([A-Z])/, (_, c) => `aria-${c.toLowerCase()}`);
const el = (tag, props = {}, children = []) => {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "dataset") Object.assign(node.dataset, value);
    else if (/^aria[A-Z]/.test(key) || key === "role") {
      if (value != null) node.setAttribute(ariaAttr(key), String(value));
    } else if (key in node) node[key] = value;
    else node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child != null && child !== false) node.append(child.nodeType ? child : document.createTextNode(child));
  }
  return node;
};
const icon = (name, cls = "ic") => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("class", cls);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
};
const iconButton = (name, label, props = {}) =>
  el("button", { className: `ic-btn ${props.className || ""}`.trim(), title: label, ...props, ariaLabel: label }, icon(name));
/* Icon buttons that change meaning must relabel BOTH channels - a screen
   reader reads aria-label, a mouse user reads the tooltip. */
const relabel = (button, iconName, label) => {
  button.replaceChildren(icon(iconName));
  button.title = label;
  button.setAttribute("aria-label", label);
};

const mq = matchMedia("(max-width: 767px)");
const isMobile = () => mq.matches;
/* `any-pointer`/`any-hover`, not `pointer`/`hover`: on a touchscreen laptop the
   primary pointer reports coarse even with a mouse attached, which would
   silently kill hover-scrub for someone who has a mouse right there. */
const canHover = matchMedia("(any-hover: hover) and (any-pointer: fine)").matches;

const fmtSize = (bytes) => {
  if (!bytes && bytes !== 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes, i = 0;
  while (value >= 1024 && i < units.length - 1) { value /= 1024; i++; }
  return `${value.toFixed(value < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
};
const fmtTime = (seconds) => {
  if (!isFinite(seconds) || seconds < 0) seconds = 0;
  const m = Math.floor(seconds / 60), s = seconds % 60;
  return `${m}:${s.toFixed(2).padStart(5, "0")}`;
};
const fmtClock = (seconds) => {
  if (!isFinite(seconds) || seconds <= 0) return "—";
  const m = Math.floor(seconds / 60), s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
};
const fmtDuration = (seconds) => (seconds ? `${seconds.toFixed(2)}s` : "—");
const fmtValue = (value) => {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
};

const getVideo = (id) => state.external.get(id) || state.videos.find((v) => v.id === id) || null;
const mediaUrl = (video) => (video.external ? video.url : `/media/${video.id}`);
/* Without a poster a <video preload="metadata"> paints solid black until playback
   starts. The server already renders thumbnails, so reuse them as the still. */
const posterUrl = (video) => (video.external ? "" : `/thumb/${video.id}`);

/* WanGP prefixes prompts with control tags and a "<something>_description:" label
   (e.g. "[/duration=5s] integrated_multimodal_description: [Shot 1] real text").
   Strip that boilerplate so titles show the part that actually differs. */
const cleanPrompt = (text) => String(text || "")
  .replace(/^\s*(?:\[[^\]]*\]\s*)+/, "")
  .replace(/^\s*[\w-]*description\s*:\s*/i, "")
  .replace(/^\s*(?:\[[^\]]*\]\s*)+/, "")
  .replace(/<((?:Subject|Picture|Image|Video|Audio)\s*\d+)>/g, "$1")
  .trim();
/* Cutting mid-word reads like a bug, so back up to the last space. */
const truncate = (text, max) => {
  if (text.length <= max) return text;
  const cut = text.slice(0, max);
  const space = cut.lastIndexOf(" ");
  return `${(space > max * 0.6 ? cut.slice(0, space) : cut).replace(/[\s,.;:—-]+$/, "")}…`;
};
/* Structured prompts ("summary:\n...\ndetailed_description:\n...") split into
   labelled sections; anything else comes back as null. */
/* WanGP writes labels as lowercase snake_case at the start of a line, either
   alone ("summary:\n...") or inline ("summary: ..."). Prose rarely does. */
const SECTION_RE = /^[ \t]*([a-z][a-z0-9]*(?:_[a-z0-9]+)*):[ \t]*/gm;
const promptSections = (text) => {
  const src = String(text || "");
  const marks = [...src.matchAll(SECTION_RE)];
  // One label counts only when it opens the text - otherwise it is just a colon in prose.
  if (!marks.length || (marks.length < 2 && src.slice(0, marks[0].index).trim())) return null;
  return marks.map((m, i) => ({
    key: m[1].trim().toLowerCase().replace(/\s+/g, "_"),
    label: m[1].replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()),
    body: src.slice(m.index + m[0].length, i + 1 < marks.length ? marks[i + 1].index : undefined).trim(),
  })).filter((section) => section.body);
};
/* The line that tells runs apart: a structured prompt's summary, not its
   boilerplate subject definitions, which are identical across a batch. */
const promptTitle = (text) => {
  const sections = promptSections(text);
  const pick = sections && (sections.find((s) => s.key === "summary")
    || sections.find((s) => /description/.test(s.key))
    || sections.find((s) => !/sound|music|audio|retention|subject/.test(s.key)) || sections[0]);
  return cleanPrompt(pick ? pick.body : text);
};
const shortName = (video, max = 110) => {
  const prompt = video.meta && video.meta.prompt ? promptTitle(video.meta.prompt) : "";
  return prompt ? truncate(prompt, max) : video.name;
};
const modelOf = (video) => (video.meta && (video.meta.model_type || video.meta.type)) || "unknown";
const durationOf = (video) => (video.probe && video.probe.duration) || 0;
const fpsOf = (video) => (video && video.probe && video.probe.fps) || 16;
const resolutionOf = (video) => (video.meta && video.meta.resolution)
  || (video.probe && video.probe.width ? `${video.probe.width}×${video.probe.height}` : null);

/* Joins values with a dimmed separator instead of baking "·" into a string. */
const dataLine = (parts) => {
  const out = [];
  parts.filter(Boolean).forEach((part, i) => {
    if (i) out.push(el("span", { className: "sep" }, "·"));
    out.push(part.nodeType ? part : el("span", {}, String(part)));
  });
  return out;
};

/* ------------------------------------------------------------------ toast */
let toastNode = null, toastTimer = 0;
function flash(message) {
  if (!toastNode) {
    toastNode = el("div", { id: "toast", role: "status" });
    document.body.append(toastNode);
  }
  toastNode.textContent = message;
  toastNode.classList.add("on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastNode.classList.remove("on"), 2200);
}
async function copy(text) {
  try { await navigator.clipboard.writeText(text); flash("Copied to clipboard"); }
  catch { flash("Copy failed"); }
}

/* ------------------------------------------------------------- data loading */
async function load(url = "/api/videos", options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  applyIndex(data);
  return data;
}

function applyIndex(data) {
  if (window.WVBGrid) data = WVBGrid.mockIndex(data);   // ?mock=N dev flag
  state.videos = data.videos || [];
  state.roots = data.roots || [];
  state.ffmpeg = !!data.ffmpeg;

  // ?compare=<id>,<id>&mode=wipe reopens a specific comparison (see "Link").
  const params = new URLSearchParams(location.search);
  const requested = params.get("compare");
  if (requested && !state.picks.length) {
    state.picks = requested.split(",").filter((id) => id && getVideo(id)).slice(0, MAX_PICKS);
    const mode = params.get("mode");
    if (["side", "wipe", "blink"].includes(mode)) { state.cmpMode = mode; state.modeTouched = true; }
    if (state.picks.length) setView("compare");
  }
  state.picks = state.picks.filter((id) => getVideo(id));
  if (!getVideo(state.activeId)) state.activeId = state.videos.length ? state.videos[0].id : null;

  const n = state.videos.length, r = state.roots.length;
  $("#status").textContent = `${n} clip${n === 1 ? "" : "s"} · ${r} folder${r === 1 ? "" : "s"}`;
  renderModelFilter();
  renderAll();
}

/* ------------------------------------------------------------------ sidebar */
/* Facets are discovered from the library itself: a filter only appears when
   the clips actually differ on it, and each option shows how many clips it
   would leave. */
const NO_LORA = "\u0000none";
const FACETS = [
  { key: "model", label: "Model", all: "All models",
    values: (v) => [Object.keys(v.meta || {}).length ? modelName(v.meta) : "No metadata"] },
  { key: "steps", label: "Steps", all: "Any steps", numeric: true,
    values: (v) => ((v.meta || {}).num_inference_steps != null ? [String(v.meta.num_inference_steps)] : []),
    show: (x) => `${x} steps` },
  { key: "res", label: "Resolution", all: "Any resolution", numeric: true,
    values: (v) => (resolutionOf(v) ? [String(resolutionOf(v)).replace("x", "×")] : []) },
  { key: "lora", label: "LoRA", all: "Any LoRA",
    values: (v) => { const l = loraList(v.meta || {}); return l.length ? l.map((x) => x.name) : [NO_LORA]; },
    show: (x) => (x === NO_LORA ? "No LoRA" : x) },
];
const facetMatch = (video, skip) => FACETS.every((f) =>
  f.key === skip || !state.facets[f.key] || f.values(video).includes(state.facets[f.key]));

function renderFacets() {
  const box = $("#facets");
  const nodes = [];
  for (const f of FACETS) {
    // Counts respect the other active filters, so options never lead to an empty list.
    const counts = new Map();
    for (const video of state.videos) {
      if (!facetMatch(video, f.key)) continue;
      for (const value of new Set(f.values(video))) counts.set(value, (counts.get(value) || 0) + 1);
    }
    const distinct = new Set(state.videos.flatMap(f.values));
    if (distinct.size < 2 && !state.facets[f.key]) continue;
    const order = [...counts.keys()].sort((a, b) => (f.numeric
      ? parseFloat(a) - parseFloat(b) || a.localeCompare(b)
      : (a === NO_LORA) - (b === NO_LORA) || counts.get(b) - counts.get(a) || a.localeCompare(b)));
    const select = el("select", {
      ariaLabel: `Filter by ${f.label.toLowerCase()}`,
      className: state.facets[f.key] ? "set" : "",
      onchange: () => { state.facets[f.key] = select.value; renderFacets(); renderList(); },
    }, [el("option", { value: "", textContent: f.all }),
      ...order.map((value) => el("option", { value, textContent: `${f.show ? f.show(value) : value}  (${counts.get(value)})` }))]);
    select.value = state.facets[f.key] || "";
    nodes.push(el("div", { className: `select compact facet c-${f.cls || { model: "model", steps: "sample", res: "shape", lora: "lora" }[f.key]}` },
      [select, icon("down")]));
  }
  const active = FACETS.filter((f) => state.facets[f.key]).length;
  if (active) {
    nodes.push(el("button", { className: "link facet-clear", onclick: () => { state.facets = {}; renderFacets(); renderList(); } },
      `Clear ${active > 1 ? `${active} filters` : "filter"}`));
  }
  box.replaceChildren(...nodes);
  box.hidden = !nodes.length;
}
const renderModelFilter = renderFacets;

function visibleVideos() {
  const query = $("#search").value.trim().toLowerCase();
  const list = state.videos.filter((video) => {
    if (!facetMatch(video)) return false;
    if (window.WVB_LIB && WVB_LIB.hidden(video)) return false;
    if (!query) return true;
    const haystack = [video.name, JSON.stringify(video.meta || {})].join(" ").toLowerCase();
    return query.split(/\s+/).every((token) => haystack.includes(token));
  });
  const by = {
    mtime: (a, b) => b.mtime - a.mtime,
    mtime_asc: (a, b) => a.mtime - b.mtime,
    name: (a, b) => a.name.localeCompare(b.name),
    size: (a, b) => b.size - a.size,
    duration: (a, b) => durationOf(b) - durationOf(a),
    gentime: (a, b) => ((b.meta || {}).generation_time || 0) - ((a.meta || {}).generation_time || 0),
  }[$("#sort").value];
  return list.sort(by);
}

function renderList() {
  const list = $("#list");
  endScrub();
  const videos = visibleVideos();
  if (!videos.length) {
    if (window.WVBGrid) WVBGrid.clear();
    list.replaceChildren(el("div", { className: "empty", style: "grid-column:1/-1" }, [
      icon("film"),
      el("h3", {}, state.videos.length ? "Nothing matches" : "No clips indexed"),
      el("p", {}, state.videos.length
        ? "Try a different search term, or clear the filters."
        : "Add the folder WanGP writes its output to and it will appear here."),
      state.videos.length ? null : el("div", { className: "row" },
        el("button", { className: "accent", onclick: () => setView("folders") }, "Add a folder")),
    ]));
    return;
  }
  if (window.WVBGrid) WVBGrid.render(videos.map((v) => ({ key: v.id, ids: [v.id], build: () => buildCard(v) })));
  else list.replaceChildren(...videos.map(buildCard));
}

function buildCard(video) {
  const pickIndex = state.picks.indexOf(video.id);
  const meta = video.meta || {};
  const hasMeta = Object.keys(meta).length > 0;
  const loras = loraList(meta);

  const thumb = el("div", { className: "thumb" });
  if (state.ffmpeg) {
    const img = el("img", { loading: "lazy", src: `/thumb/${video.id}`, alt: "" });
    img.onerror = () => img.replaceWith(icon("image"));
    thumb.append(img);
  } else {
    thumb.append(icon("image"));
  }
  thumb.append(el("i", { className: "scrubline" }));
  if (durationOf(video)) thumb.append(el("span", { className: "thumb-dur" }, fmtClock(durationOf(video))));
  attachScrub(thumb, video);

  const pick = el("button", {
    className: `pick${pickIndex >= 0 ? " on" : ""}`,
    ariaLabel: pickIndex >= 0 ? `Remove from compare (currently #${pickIndex + 1})` : "Add to compare",
    title: pickIndex >= 0 ? "Remove from compare" : "Add to compare",
    onclick: (event) => { event.stopPropagation(); togglePick(video.id); },
  }, pickIndex >= 0 ? String(pickIndex + 1) : icon("plus"));

  const when = new Date(video.mtime * 1000).toLocaleString([], {
    month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
  });

  // The card is the app's primary control, so it has to be operable from the
  // keyboard. The pick button is a sibling rather than a descendant so we never
  // nest one control inside another.
  const card = el("div", {
    className: `card${video.id === state.activeId ? " active" : ""}${pickIndex >= 0 ? " picked" : ""}`,
    role: "button",
    tabIndex: 0,
    ariaCurrent: video.id === state.activeId ? "true" : null,
    ariaLabel: `${shortName(video, 70)} — seed ${meta.seed ?? "unknown"}`,
    onclick: () => openPreview(video.id),
    ondblclick: () => togglePick(video.id),
    onkeydown: (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openPreview(video.id); }
    },
  }, [
    thumb,
    el("div", { className: "card-body" }, [
      el("div", { className: "card-title" }, shortName(video)),
      hasMeta ? el("div", { className: "card-model", title: modelName(meta) }, modelName(meta)) : null,
      el("div", { className: "card-data" }, dataLine([
        meta.num_inference_steps != null ? el("span", { className: "c-sample" }, `${meta.num_inference_steps} steps`) : null,
        resolutionOf(video) ? el("span", { className: "c-shape" }, String(resolutionOf(video)).replace("x", "×")) : null,
        meta.seed != null ? el("span", { className: "c-seed", title: "Seed" }, String(meta.seed)) : null,
      ])),
      loras.length ? el("div", { className: "card-loras c-lora", title: loras.map((l) => `${l.name}${l.weight ? ` × ${l.weight}` : ""}`).join("\n") },
        [el("span", { className: "card-lora" }, loras[0].name), loras.length > 1 ? el("b", {}, `+${loras.length - 1}`) : null]) : null,
      el("div", { className: "card-foot" }, `${when} · ${fmtSize(video.size)}`),
    ]),
  ]);
  if (window.WVB_LIB) WVB_LIB.decorateCard(card, video);
  return el("div", { className: "card-slot", role: "listitem" }, [card, pick]);
}

/* -------------------------------------------------------------- hover scrub
   Sweeping across a thumbnail scrubs that clip, so a run can be identified
   without opening it. One shared element, promoted into whichever thumb is
   hovered - a <video> per card would open a connection per card. */
let scrubVideo = null, scrubOwner = null, scrubRaf = 0, scrubRatio = 0, scrubDuration = 0;

function ensureScrubVideo() {
  if (scrubVideo) return scrubVideo;
  scrubVideo = el("video", { muted: true, playsInline: true, preload: "auto" });
  scrubVideo.setAttribute("aria-hidden", "true");
  return scrubVideo;
}

function attachScrub(thumb, video) {
  if (!canHover || video.external) return;
  thumb.addEventListener("pointerenter", (event) => {
    if (event.pointerType === "touch") return;
    beginScrub(thumb, video);
    moveScrub(event);
  });
  thumb.addEventListener("pointermove", (event) => { if (scrubOwner === thumb) moveScrub(event); });
  thumb.addEventListener("pointerleave", () => { if (scrubOwner === thumb) endScrub(); });
}

function beginScrub(thumb, video) {
  if (scrubOwner === thumb) return;
  endScrub();
  scrubOwner = thumb;
  scrubDuration = durationOf(video);
  const node = ensureScrubVideo();
  node.src = mediaUrl(video);
  thumb.append(node);
  thumb.classList.add("scrubbing");
  // Grid tiles hover-play (muted, looping) instead of scrubbing.
  node.loop = hoverPlays();
  if (node.loop) node.play().catch(() => {});
}
const hoverPlays = () => document.documentElement.dataset.layout === "grid";

function moveScrub(event) {
  if (!scrubOwner || hoverPlays()) return;
  const rect = scrubOwner.getBoundingClientRect();
  scrubRatio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
  if (scrubRaf) return;
  scrubRaf = requestAnimationFrame(() => {
    scrubRaf = 0;
    if (!scrubOwner || !scrubVideo) return;
    const total = scrubDuration || scrubVideo.duration || 0;
    if (total) scrubVideo.currentTime = scrubRatio * total;
    const line = scrubOwner.querySelector(".scrubline");
    if (line) line.style.width = `${scrubRatio * 100}%`;
  });
}

function endScrub() {
  if (scrubRaf) { cancelAnimationFrame(scrubRaf); scrubRaf = 0; }
  if (scrubOwner) {
    scrubOwner.classList.remove("scrubbing");
    const line = scrubOwner.querySelector(".scrubline");
    if (line) line.style.width = "0";
    scrubOwner = null;
  }
  if (scrubVideo) {
    scrubVideo.remove();
    scrubVideo.removeAttribute("src");
    scrubVideo.load();       // drops the in-flight range request
  }
}

/* ------------------------------------------------------------------- picks */
function togglePick(id) {
  const index = state.picks.indexOf(id);
  if (index >= 0) state.picks.splice(index, 1);
  else if (state.picks.length < MAX_PICKS) state.picks.push(id);
  else return flash(`Compare holds at most ${MAX_PICKS} clips.`);
  renderAll();
}

function openPreview(id) {
  state.activeId = id;
  state.sheet = true;
  setView("preview");
  renderAll();
  $("#view-preview").scrollTop = 0;
}

/* ==========================================================================
   Transport - one instrument, used both as the preview player's overlay bar
   and as the shared bar that drives a comparison.
   ========================================================================== */
function createTransport(players, opts = {}) {
  const {
    variant = "dock", videos = [], extras = [], fullscreenTarget = null,
    mute = "none", onTick = null,   // "none" | "local" (one clip) | "solo" (pick one of many)
    frames = false,                 // fold the frame number into the readout
  } = opts;
  const master = () => players[0];
  const fps = () => fpsOf(videos[0]) || 16;

  const totalDuration = () => {
    const fromPlayers = players.reduce((max, p) => Math.max(max, isFinite(p.duration) ? p.duration : 0), 0);
    if (fromPlayers > 0) return fromPlayers;
    return videos.reduce((max, v) => Math.max(max, durationOf(v)), 0);
  };
  const seekAll = (time) => players.forEach((p) => {
    p.currentTime = Math.max(0, Math.min(time, (p.duration || time) - 0.001));
  });
  const playAll = () => players.forEach((p) => p.play().catch((error) => {
    // AbortError just means a seek interrupted the play; anything else is worth
    // saying out loud rather than leaving the button looking broken.
    if (error && error.name !== "AbortError") flash(`Playback blocked: ${error.message.split(".")[0]}`);
  }));
  const pauseAll = () => players.forEach((p) => p.pause());
  const stepFrames = (delta) => { pauseAll(); seekAll(master().currentTime + delta / fps()); };

  const toggle = () => (master().paused ? playAll() : pauseAll());
  const playBtn = iconButton("play", "Play", { onclick: toggle });
  const startBtn = iconButton("start", "Back to start", { onclick: () => seekAll(0) });
  const backBtn = el("button", { className: "sm step", title: "Step back one frame", ariaLabel: "Step back one frame", onclick: () => stepFrames(-1) }, "−1f");
  const fwdBtn = el("button", { className: "sm step", title: "Step forward one frame", ariaLabel: "Step forward one frame", onclick: () => stepFrames(1) }, "+1f");

  const rail = el("div", { className: "track-rail" });
  const buf = el("div", { className: "track-buf" });
  const fill = el("div", { className: "track-fill" });
  const knob = el("div", { className: "track-knob" });
  const bubble = el("div", { className: "track-bubble" }, "0:00.00");
  const track = el("div", {
    className: "track", role: "slider", tabIndex: 0,
    ariaLabel: "Seek", ariaValueMin: "0", ariaValueMax: "100", ariaValueNow: "0",
  }, [rail, buf, fill, knob, bubble]);

  const ratioAt = (clientX) => {
    const rect = track.getBoundingClientRect();
    return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
  };
  const showBubble = (ratio) => {
    bubble.style.left = `${ratio * 100}%`;
    bubble.textContent = fmtTime(ratio * totalDuration());
  };
  track.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    track.setPointerCapture(event.pointerId);
    track.classList.add("dragging");
    seekAll(ratioAt(event.clientX) * totalDuration());
  });
  track.addEventListener("pointermove", (event) => {
    const ratio = ratioAt(event.clientX);
    showBubble(ratio);
    if (track.classList.contains("dragging")) seekAll(ratio * totalDuration());
  });
  const release = () => track.classList.remove("dragging");
  track.addEventListener("pointerup", release);
  track.addEventListener("pointercancel", release);
  track.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") { event.preventDefault(); stepFrames(event.shiftKey ? -10 : -1); }
    else if (event.key === "ArrowRight") { event.preventDefault(); stepFrames(event.shiftKey ? 10 : 1); }
  });

  const readout = el("span", { className: "tc" }, [el("b", {}, "0:00.00"), " / 0:00.00"]);

  const speed = el("select", {
    ariaLabel: "Playback speed",
    onchange: (event) => {
      state.rate = parseFloat(event.target.value);
      players.forEach((p) => { p.playbackRate = state.rate; });
    },
  }, [0.25, 0.5, 1, 1.5, 2].map((rate) =>
    el("option", { value: rate, textContent: `${rate}×`, selected: rate === state.rate })));
  const speedWrap = el("div", { className: "select compact", style: "flex:none;width:auto" }, [speed, icon("down")]);

  const loopBtn = iconButton("loop", "Loop", { className: "toggle" });
  const syncLoop = () => {
    // The tint alone would be the only signal that looping is on, so the glyph
    // changes as well.
    relabel(loopBtn, state.loop ? "loop" : "loop-off", state.loop ? "Looping — click to play once" : "Play once — click to loop");
    loopBtn.setAttribute("aria-pressed", String(state.loop));
  };
  loopBtn.onclick = () => { state.loop = !state.loop; syncLoop(); };
  syncLoop();

  const controls = [playBtn, startBtn, backBtn, fwdBtn, track, readout, speedWrap, loopBtn];

  if (mute !== "none") {
    // "local": a lone clip owns its own audio and starts audible.
    // "solo": one of several clips is allowed to make noise, chosen globally.
    const muteBtn = iconButton("volume", "Mute", { className: "toggle" });
    const isOn = () => (mute === "local" ? !master().muted : state.unmuted === 0);
    const syncMute = () => {
      const on = isOn();
      relabel(muteBtn, on ? "volume" : "mute", on ? "Mute" : "Unmute");
      muteBtn.setAttribute("aria-pressed", String(on));
    };
    muteBtn.onclick = () => {
      if (mute === "local") master().muted = !master().muted;
      else { state.unmuted = state.unmuted === 0 ? null : 0; applyMute(players); }
      syncMute();
    };
    if (mute === "local") master().muted = false;
    controls.push(muteBtn);
    syncMute();
  }
  if (fullscreenTarget) {
    controls.push(iconButton("expand", "Fullscreen", {
      onclick: () => {
        if (document.fullscreenElement) document.exitFullscreen();
        else fullscreenTarget.requestFullscreen && fullscreenTarget.requestFullscreen();
      },
    }));
  }
  controls.push(...extras);

  const node = el("div", { className: `transport ${variant}` }, controls);

  players.forEach((p) => {
    p.playbackRate = state.rate;
    p.onended = () => { if (state.loop) { seekAll(0); playAll(); } else pauseAll(); };
  });

  // One loop keeps the bar, the per-clip stamps and the follower clips in step.
  let raf = 0;
  const tick = () => {
    if (!node.isConnected) return;
    const lead = master();
    if (lead) {
      const total = totalDuration();
      const ratio = total ? lead.currentTime / total : 0;
      fill.style.width = `${ratio * 100}%`;
      knob.style.left = `${ratio * 100}%`;
      const buffered = lead.buffered.length ? lead.buffered.end(lead.buffered.length - 1) : 0;
      buf.style.width = total ? `${Math.min(1, buffered / total) * 100}%` : "0";
      readout.replaceChildren(...[
        el("b", {}, fmtTime(lead.currentTime)),
        frames ? el("span", { className: "frame" }, ` f${Math.round(lead.currentTime * fps())}`) : null,
        ` / ${fmtTime(total)}`,
      ].filter(Boolean));
      track.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
      track.setAttribute("aria-valuetext", `${fmtTime(lead.currentTime)} of ${fmtTime(total)}`);
      const wantPlayIcon = lead.paused ? "play" : "pause";
      if (playBtn.dataset.icon !== wantPlayIcon) {
        playBtn.dataset.icon = wantPlayIcon;
        relabel(playBtn, wantPlayIcon, lead.paused ? "Play" : "Pause");
      }
      if (onTick) onTick(lead.currentTime);
      for (const follower of players.slice(1)) {
        if (Math.abs(follower.currentTime - lead.currentTime) > 0.12 && follower.duration > lead.currentTime) {
          follower.currentTime = lead.currentTime;
        }
      }
    }
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);

  return { node, playAll, pauseAll, toggle, seekAll, stepFrames, stop: () => cancelAnimationFrame(raf) };
}

const applyMute = (players) => players.forEach((p, i) => { p.muted = state.unmuted !== i; });

/* --------------------------------------------------------- preview player */
function buildPlayer(video) {
  const media = el("video", {
    preload: "metadata", playsInline: true, poster: posterUrl(video), src: mediaUrl(video),
    ariaLabel: shortName(video),
  });
  // Purely a visual affordance - the click target is the video itself.
  const bigPlay = el("div", { className: "big-play", ariaHidden: "true" }, icon("play"));

  // A single clip needs no per-cell stamp - the frame number belongs in the
  // readout, where it doesn't fight the controls for the bottom-left corner.
  const transport = createTransport([media], {
    variant: "overlay", videos: [video], mute: "local", frames: true,
  });

  const player = el("div", { className: "player" },
    [media, el("div", { className: "player-scrim" }), bigPlay, transport.node]);

  transport.node.append(iconButton("expand", "Fullscreen", {
    onclick: () => {
      if (document.fullscreenElement) document.exitFullscreen();
      else player.requestFullscreen && player.requestFullscreen();
    },
  }));

  // The bar hides while playing and returns on intent - the footage is the point.
  let hideTimer = 0;
  const reveal = () => {
    player.classList.add("show-bar");
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => { if (!media.paused) player.classList.remove("show-bar"); }, 2200);
  };
  player.addEventListener("pointermove", reveal);
  player.addEventListener("pointerleave", () => { if (!media.paused) player.classList.remove("show-bar"); });
  media.addEventListener("play", () => { player.classList.add("playing"); reveal(); });
  media.addEventListener("pause", () => { player.classList.remove("playing"); player.classList.add("show-bar"); });
  media.addEventListener("click", () => (media.paused ? media.play().catch(() => {}) : media.pause()));
  player.classList.add("show-bar");

  return { player, media, transport };
}

/* ------------------------------------------------------------------ preview */
function renderPreview() {
  const view = $("#view-preview");
  const video = getVideo(state.activeId);
  if (!video) {
    view.replaceChildren(el("div", { className: "empty" }, [
      icon("film"),
      el("h3", {}, "Nothing selected"),
      el("p", {}, "Pick a clip from the library to see its frames and the settings it was generated with."),
    ]));
    return;
  }
  const meta = video.meta || {};
  const probe = video.probe || {};
  const pickIndex = state.picks.indexOf(video.id);

  const head = el("div", { className: "preview-head" }, [
    el("div", { className: "preview-id" }, [
      el("div", { className: "preview-model" }, Object.keys(meta).length ? modelName(meta) : "No WanGP metadata"),
      el("h2", { className: "preview-title" }, shortName(video, 160)),
    ]),
    el("div", { className: "preview-actions" }, [
      el("button", {
        className: `ghost${pickIndex >= 0 ? " on" : ""}`,
        onclick: () => togglePick(video.id),
      }, [icon(pickIndex >= 0 ? "check" : "compare"),
        pickIndex >= 0 ? `In compare · ${pickIndex + 1}` : "Compare"]),
      iconButton("drop", "Compare against a file from anywhere", { className: "ghost", onclick: () => $("#filePicker").click() }),
    ]),
    window.WVB_LIB && !video.external ? WVB_LIB.previewBar(video) : null,
  ]);

  const { player } = buildPlayer(video);
  const hasMeta = Object.keys(meta).length > 0;

  /* ---- Recipe. No headings and no boxes: each value is set in its category's
     colour with a quiet word after it, and copies itself on click. */
  const fact = (key, value, unit, cat, copyValue) => {
    if (value === null || value === undefined || value === "—" || value === "") return null;
    return el("button", {
      className: `fact c-${cat}`, title: `${labelOf(key)} — click to copy`,
      onclick: () => copy(String(copyValue ?? value)),
    }, [el("b", {}, String(value)), unit ? el("span", {}, unit) : null]);
  };
  const val = (key) => (meta[key] === undefined ? null : displayValue(key, meta[key], video));
  const guidance = ["guidance_scale", "guidance2_scale", "guidance3_scale"]
    .filter((key) => !isBlank(meta[key])).map((key) => meta[key]).join(" / ") || null;
  const frames = Number(meta.video_length);
  const loras = loraList(meta);

  const recipe = hasMeta ? el("div", { className: "recipe" }, [
    meta.seed != null ? el("button", { className: "seed c-seed", title: "Seed — click to copy", onclick: () => copy(String(meta.seed)) },
      [el("b", {}, String(meta.seed)), el("span", {}, "seed")]) : null,
    el("div", { className: "facts" }, [
      fact("num_inference_steps", val("num_inference_steps"), "steps", "sample"),
      fact("guidance_scale", guidance, "guidance", "sample"),
      fact("flow_shift", val("flow_shift"), "shift", "sample"),
      fact("sample_solver", val("sample_solver"), "solver", "sample"),
      fact("resolution", meta.resolution ? String(meta.resolution).replace("x", "×") : null, null, "shape", meta.resolution),
      fact("video_length", isFinite(frames) && frames > 0 ? frames : null,
        `frames · ${(frames / fpsOf(video)).toFixed(1)} s`, "shape"),
      fact("generation_time", val("generation_time"), "to render", "time", meta.generation_time),
    ].filter(Boolean)),
    loras.length ? el("ul", { className: "loras" }, loras.map((lora) => el("li", { className: "c-lora", title: lora.name }, [
      el("span", { className: "lora-name" }, lora.name),
      lora.weight ? el("span", { className: "lora-w" }, `× ${lora.weight}`) : null,
    ]))) : null,
  ]) : null;

  /* ---- Prompt. Sections are told apart by a coloured rule, not a heading;
     the summary leads because it is what distinguishes one run from the next. */
  const SECTION_ORDER = ["summary", "detailed_description", "subject_definitions", "retention_analysis"];
  const sectionCat = (key) => (key === "summary" ? "seed" : /description/.test(key) ? "sample"
    : /subject|retention/.test(key) ? "lora" : /sound|music|audio/.test(key) ? "time" : "shape");
  const promptBlock = (key, label, text, primary) => {
    if (isBlank(text)) return null;
    let sections = primary ? promptSections(text) : null;
    if (sections) {
      const rank = (s) => { const i = SECTION_ORDER.indexOf(s.key); return i < 0 ? 99 : i; };
      sections = sections.filter((s) => !/^n\/?a\.?$/i.test(s.body)).sort((x, y) => rank(x) - rank(y));
    }
    const body = sections
      ? el("div", { className: "prose sections" }, sections.map((section) => el("p", {
        className: `psec c-${sectionCat(section.key)}${section.key === "summary" ? " lead" : ""}`, title: section.label,
      }, placeholders(section.body.replace(/^\s*(?:\[[^\]]*generation[^\]]*\]\s*)+/i, "")))))
      : el("div", { className: `prose${primary ? "" : " minor"}`, title: label }, placeholders(String(text).trim()));
    const long = String(text).length > 900;
    if (long) body.classList.add("clamp");
    const more = long ? el("button", { className: "link", onclick: () => {
      const open = body.classList.toggle("open");
      more.textContent = open ? "Show less" : "Show full prompt";
    } }, "Show full prompt") : null;
    return el("section", { className: `prompt${primary ? "" : " minor"}` }, [
      primary ? null : el("div", { className: "neg-mark" }, label),
      iconButton("copy", `Copy ${label.toLowerCase()}`, { className: "sm ghost corner", onclick: () => copy(String(text)) }),
      body, more,
    ]);
  };
  const prompts = [
    promptBlock("prompt", "Prompt", meta.prompt, true),
    promptBlock("negative_prompt", "Negative prompt", meta.negative_prompt),
    promptBlock("alt_prompt", "Alt prompt", meta.alt_prompt),
  ].filter(Boolean);

  /* ---- Everything else: one list, group shown by a coloured dot rather than a
     heading. Blank values (most of WanGP's ~50 keys on any run) stay hidden. */
  const GROUP_CAT = { "Model": "model", "Generation": "sample", "Speed / cache": "time", "LoRAs": "lora",
    "Sliding window": "shape", "Prompt / inputs": "lora", "Post-processing": "post", "Output": "time", "Other": "model" };
  const shown = new Set(["seed", "num_inference_steps", "guidance_scale", "guidance2_scale", "guidance3_scale",
    "flow_shift", "sample_solver", "resolution", "video_length", "generation_time", "type",
    "activated_loras", "loras_multipliers", "prompt", "negative_prompt", "alt_prompt"]);
  const settings = el("div", { className: "settings" });
  const buildSettings = () => {
    const groups = [...GROUPS, ["Other", Object.keys(meta).filter((key) => !GROUPED_KEYS.has(key)).sort()]];
    let blanks = 0;
    const rows = [];
    for (const [title, keys] of groups) {
      for (const key of keys) {
        if (shown.has(key) || HIDDEN_KEYS.has(key) || meta[key] === undefined) continue;
        const blank = isBlank(parseLoose(meta[key]));
        if (blank) blanks++;
        if (blank && !state.showBlank) continue;
        let text = displayValue(key, meta[key], video);
        if (/^\S{28,}$/.test(text)) text = text.replace(/([_\-.])/g, "$1\u200b");
        rows.push(el("dt", { className: `c-${GROUP_CAT[title] || "model"}`, title: `${title} · ${key}` }, labelOf(key)),
          el("dd", { className: `${blank ? "blank" : ""}${text.includes("\n") ? " multi" : ""}`, title: String(meta[key]) }, text));
      }
    }
    const raw = JSON.stringify(meta, null, 2);
    settings.replaceChildren(
      el("dl", { className: "kv" }, rows),
      el("div", { className: "links" }, [
        blanks ? el("button", { className: "link", onclick: () => { state.showBlank = !state.showBlank; buildSettings(); } },
          state.showBlank ? "Hide empty settings" : `Show ${blanks} empty settings`) : null,
        el("button", { className: "link", onclick: () => copy(raw) }, "Copy as JSON"),
      ]),
    );
  };
  if (hasMeta) buildSettings();

  /* ---- File: a footnote, not a section. */
  const folder = video.external ? "(dropped file)" : (video.path || "").slice(0, -(video.name.length + 1));
  const stream = [fmtSize(video.size), `${fmtDuration(probe.duration)}${probe.fps ? ` @ ${probe.fps} fps` : ""}`,
    probe.codec, probe.bitrate && `${Math.round(probe.bitrate / 1000)} kbps`,
    probe.has_audio ? `audio ${probe.audio_codec}` : "no audio"].filter(Boolean).join(" · ");
  const file = el("div", { className: "file" }, [
    el("button", { className: "filename", title: "Copy full path", onclick: () => copy(video.path || video.name) }, video.name),
    el("div", { className: "file-path", title: folder }, folder),
    el("div", { className: "file-meta" }, stream),
  ]);

  const noMeta = hasMeta ? null : el("p", { className: "note" },
    "This file carries no WanGP metadata. Turn on metadata output in WanGP's settings and future clips will show their full recipe here.");

  view.replaceChildren(el("div", { className: "preview" }, [
    head,
    el("div", { className: "preview-main" }, [player, ...prompts]),
    el("aside", { className: "preview-side" }, [recipe, noMeta, hasMeta ? settings : null, file].filter(Boolean)),
  ]));
}

function panel(title, body, tools = [], wide = false) {
  return el("div", { className: `panel${wide ? " wide" : ""}` }, [
    el("div", { className: "panel-head" }, [el("h3", {}, title), el("div", { className: "tools" }, tools)]),
    ...[].concat(body).map((node) =>
      node.classList && (node.classList.contains("kv") || node.classList.contains("panel-body"))
        ? node : el("div", { className: "panel-body" }, node)),
  ]);
}
const dl = (rows) => el("dl", { className: "kv" },
  rows.flatMap(([key, value]) => [el("dt", {}, key), el("dd", {}, String(value))]));

/* ------------------------------------------------------------------ compare */
let cmpTransport = null;
let blinkStack = null;
let blinkTimer = 0;

function stopCompare() {
  if (blinkTimer) clearInterval(blinkTimer);
  blinkTimer = 0;
  blinkStack = null;
  if (cmpTransport) cmpTransport.stop();
  cmpTransport = null;
}

/* While flickering, the one thing the eye cannot infer is which clip it is
   looking at - so the live tag is always marked. */
function syncBlinkTags() {
  if (!blinkStack) return;
  blinkStack.classList.toggle("flip", state.blinkFlip);
  const [tagA, tagB] = blinkStack.querySelectorAll(".tag");
  if (tagA) tagA.classList.toggle("live", !state.blinkFlip);
  if (tagB) tagB.classList.toggle("live", state.blinkFlip);
}
function toggleBlink() { state.blinkFlip = !state.blinkFlip; syncBlinkTags(); }

function clipData(video) {
  const meta = video.meta || {};
  return dataLine([
    meta.seed != null ? el("span", { className: "c-seed" }, String(meta.seed)) : null,
    resolutionOf(video) ? el("span", { className: "c-shape" }, String(resolutionOf(video)).replace("x", "×")) : null,
    meta.num_inference_steps != null ? el("span", { className: "c-sample" }, `${meta.num_inference_steps} steps`) : null,
    durationOf(video) ? el("span", { className: "c-time" }, fmtDuration(durationOf(video))) : null,
    Object.keys(meta).length ? modelName(meta) : null,
  ]);
}

function buildSideBySide(videos, players, stamps) {
  const cells = videos.map((video, index) => {
    const media = el("video", {
      preload: "metadata", muted: true, playsInline: true,
      poster: posterUrl(video), src: mediaUrl(video), ariaLabel: `Clip ${index + 1}`,
    });
    players.push(media);
    const stamp = el("span", { className: "stamp" }, [
      el("span", { className: "t" }, "0:00.00"), " ", el("span", { className: "frame" }, "f0"),
    ]);
    stamps.push({ node: stamp, fps: fpsOf(video), index });

    const audio = iconButton("mute", "Solo audio", { className: "sm toggle" });
    const syncAudio = () => {
      const on = state.unmuted === index;
      relabel(audio, on ? "volume" : "mute", on ? `Mute clip ${index + 1}` : `Play sound from clip ${index + 1}`);
      audio.setAttribute("aria-pressed", String(on));
    };
    audio.onclick = () => {
      state.unmuted = state.unmuted === index ? null : index;
      applyMute(players);
      document.querySelectorAll(".cmp-audio").forEach((b) => b.dispatchEvent(new Event("sync")));
    };
    audio.classList.add("cmp-audio");
    audio.addEventListener("sync", syncAudio);
    syncAudio();

    return el("div", { className: "cmp-cell" }, [
      el("div", { className: "cmp-bar" }, [
        el("span", { className: "idx" }, String(index + 1)),
        el("span", { className: "cmp-label", title: video.name }, shortName(video)),
        audio,
        iconButton("close", `Remove clip ${index + 1}`, { className: "sm ghost", onclick: () => togglePick(video.id) }),
      ]),
      el("div", { className: "cmp-media" }, [media, stamp]),
      el("div", { className: "cmp-data" }, clipData(video)),
    ]);
  });
  return el("div", { className: `cmp-grid n${videos.length}` }, cells);
}

function buildStack(videos, players, stamps) {
  const [first, second] = videos;
  // players[0] stays the master clock regardless of DOM stacking order.
  const over = el("video", { className: "over", preload: "metadata", muted: true, playsInline: true,
    poster: posterUrl(first), src: mediaUrl(first), ariaLabel: "Clip 1" });
  const under = el("video", { className: "under", preload: "metadata", muted: true, playsInline: true,
    poster: posterUrl(second), src: mediaUrl(second), ariaLabel: "Clip 2" });
  players.push(over, under);

  const stamp = el("span", { className: "stamp" }, [
    el("span", { className: "t" }, "0:00.00"), " ", el("span", { className: "frame" }, "f0"),
  ]);
  stamps.push({ node: stamp, fps: fpsOf(first), index: 0 });

  const label = (video, n) => `#${n}${(video.meta || {}).seed != null ? ` ${video.meta.seed}` : ""}`;
  const tagA = el("span", { className: "tag a" }, label(first, 1));
  const tagB = el("span", { className: "tag b" }, label(second, 2));

  const stack = el("div", { className: `stack${state.cmpMode === "blink" ? " blink" : ""}` },
    [under, over, tagA, tagB, stamp]);
  stack.style.setProperty("--wipe", `${state.wipe}%`);

  if (state.cmpMode === "wipe") {
    const handle = el("div", {
      className: "wipe-handle", role: "slider", tabIndex: 0,
      ariaLabel: "Wipe divider between clip 1 and clip 2",
      ariaValueMin: "0", ariaValueMax: "100",
    }, el("div", { className: "wipe-grip" }, icon("wipe")));
    stack.append(handle);
    const setWipe = (percent) => {
      state.wipe = Math.max(0, Math.min(100, percent));
      stack.style.setProperty("--wipe", `${state.wipe}%`);
      handle.setAttribute("aria-valuenow", String(Math.round(state.wipe)));
      handle.setAttribute("aria-valuetext", `${Math.round(state.wipe)}% clip 1`);
    };
    setWipe(state.wipe);
    // Dragging is the obvious gesture, but it must not be the only one.
    handle.addEventListener("keydown", (event) => {
      const step = event.shiftKey ? 10 : 2;
      if (event.key === "ArrowLeft") { event.preventDefault(); setWipe(state.wipe - step); }
      else if (event.key === "ArrowRight") { event.preventDefault(); setWipe(state.wipe + step); }
      else if (event.key === "Home") { event.preventDefault(); setWipe(0); }
      else if (event.key === "End") { event.preventDefault(); setWipe(100); }
    });
    const moveTo = (clientX) => {
      const rect = stack.getBoundingClientRect();
      setWipe(((clientX - rect.left) / rect.width) * 100);
    };
    stack.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      stack.setPointerCapture(event.pointerId);
      moveTo(event.clientX);
      const onMove = (moveEvent) => moveTo(moveEvent.clientX);
      const onUp = () => {
        stack.removeEventListener("pointermove", onMove);
        stack.removeEventListener("pointerup", onUp);
        stack.removeEventListener("pointercancel", onUp);
      };
      stack.addEventListener("pointermove", onMove);
      stack.addEventListener("pointerup", onUp);
      stack.addEventListener("pointercancel", onUp);
    });
  } else {
    blinkStack = stack;
    syncBlinkTags();
    if (state.blinkMs) {
      blinkTimer = setInterval(() => { state.blinkFlip = !state.blinkFlip; syncBlinkTags(); }, state.blinkMs);
    }
  }
  return stack;
}

function renderCompare() {
  const view = $("#view-compare");
  stopCompare();
  const videos = state.picks.map(getVideo).filter(Boolean);

  if (!videos.length) {
    view.replaceChildren(el("div", { className: "empty" }, [
      icon("compare"),
      el("h3", {}, "Nothing to compare yet"),
      el("p", {}, "Pick up to four clips from the library — hit the + on a card, or double-click it. With exactly two picked you also get wipe and blink, which overlay both clips in the same place."),
      el("div", { className: "row" }, [
        el("button", { className: "accent", onclick: () => { state.picks = visibleVideos().slice(0, 2).map((v) => v.id); renderAll(); } },
          "Compare the two newest"),
        el("button", { onclick: () => $("#filePicker").click() }, [icon("drop"), "Load a file"]),
      ]),
    ]));
    return;
  }

  // Wipe and blink overlay two clips - they have no meaning for other counts.
  const stackable = videos.length === 2;
  if (!stackable) state.cmpMode = "side";
  // Two 195px-wide frames tell you nothing, so a phone starts in wipe.
  else if (!state.modeTouched && isMobile() && state.cmpMode === "side") state.cmpMode = "wipe";

  const players = [];
  const stamps = [];
  const stage = state.cmpMode === "side"
    ? buildSideBySide(videos, players, stamps)
    : buildStack(videos, players, stamps);

  const modeSwitch = el("div", { className: "mode-switch", role: "group", ariaLabel: "Comparison mode" },
    [["side", "Side by side", "compare"], ["wipe", "Wipe", "wipe"], ["blink", "Blink", "blink"]]
      .map(([mode, label, ic]) => {
        const button = el("button", {
          disabled: mode !== "side" && !stackable,
          title: mode !== "side" && !stackable ? "Pick exactly two clips to use this mode" : label,
          // The label is hidden on mobile, and display:none text contributes no
          // accessible name - so the name is set explicitly.
          ariaLabel: label,
          onclick: () => { state.cmpMode = mode; state.modeTouched = true; renderCompare(); },
        }, [icon(ic), el("span", { className: "only-desktop" }, label)]);
        button.setAttribute("aria-pressed", String(state.cmpMode === mode));
        return button;
      }));

  const extras = [modeSwitch];
  if (state.cmpMode === "blink") {
    extras.push(el("button", { className: "sm", title: "Swap which clip is showing (B)", onclick: toggleBlink }, "Swap"));
    const select = el("select", {
      ariaLabel: "Auto-flicker speed",
      onchange: (event) => { state.blinkMs = parseInt(event.target.value, 10); renderCompare(); },
    }, [[0, "Manual"], [1000, "1s"], [500, "0.5s"], [200, "0.2s"]].map(([ms, text]) =>
      el("option", { value: ms, textContent: text, selected: ms === state.blinkMs })));
    extras.push(el("div", { className: "select compact", style: "flex:none;width:auto" }, [select, icon("down")]));
  }
  extras.push(iconButton("link", "Copy a link that reopens this comparison", { onclick: () => copy(compareLink()) }));

  cmpTransport = createTransport(players, {
    variant: "dock",
    videos,
    extras,
    // Side-by-side has a solo button per cell; the stacked modes have one place
    // for it, so the shared bar carries it instead.
    mute: state.cmpMode === "side" ? "none" : "solo",
    onTick: (time) => {
      for (const { node, fps, index } of stamps) {
        const at = (players[index] || players[0]).currentTime;
        node.firstChild.textContent = fmtTime(at);
        node.lastChild.textContent = `f${Math.round(at * (fps || 16))}`;
      }
      void time;
    },
  });
  applyMute(players);

  view.replaceChildren(el("div", { className: "cmp" }, [stage, cmpTransport.node, buildDiff(videos)]));
}

/* Only indexed clips have stable ids; dropped files cannot be linked to. */
const compareLink = () =>
  `${location.origin}/?compare=${state.picks.filter((id) => !id.startsWith("local:")).join(",")}&mode=${state.cmpMode}`;

/* ==========================================================================
   Settings diff
   ========================================================================== */

/* Each token is a word plus the whitespace that follows it, so concatenating
   them reproduces the original text exactly. Splitting whitespace into tokens
   of its own would quadruple the comparison table, fragment every highlight,
   and - because every space matches every other space - make two unrelated
   prompts look ~45% similar. */
const tokenize = (text) => {
  const raw = String(text).match(/\S+\s*/g) || [];
  return { raw, key: raw.map((t) => t.trimEnd()), lead: String(text).match(/^\s*/)[0] };
};

function wordDiff(a, b) {
  const ta = tokenize(a), tb = tokenize(b);
  const A = ta.key, B = tb.key;
  if (!A.length || !B.length) return null;

  // Two runs of the same prompt usually share a long head and tail. Peeling
  // those off first is what keeps the quadratic table small enough to matter -
  // a pair of 600-token prompts is 360k cells before trimming, and often only
  // a few hundred after.
  let head = 0;
  while (head < A.length && head < B.length && A[head] === B[head]) head++;
  let tail = 0;
  while (tail < A.length - head && tail < B.length - head
         && A[A.length - 1 - tail] === B[B.length - 1 - tail]) tail++;

  const m = A.length - head - tail, n = B.length - head - tail;
  if (m * n > 1500000) return null;   // ~6 MB table; beyond this, plain text

  let dp = new Uint32Array(0);
  const width = n + 1;
  if (m > 0 && n > 0) {
    dp = new Uint32Array((m + 1) * width);
    for (let i = m - 1; i >= 0; i--) {
      for (let j = n - 1; j >= 0; j--) {
        dp[i * width + j] = A[head + i] === B[head + j]
          ? dp[(i + 1) * width + (j + 1)] + 1
          : Math.max(dp[(i + 1) * width + j], dp[i * width + (j + 1)]);
      }
    }
  }

  const left = [], right = [];
  if (ta.lead) { left.push([ta.lead, 0]); }
  if (tb.lead) { right.push([tb.lead, 0]); }
  for (let k = 0; k < head; k++) { left.push([ta.raw[k], 0]); right.push([tb.raw[k], 0]); }

  let i = 0, j = 0, kept = head + tail;
  while (i < m && j < n) {
    if (A[head + i] === B[head + j]) {
      left.push([ta.raw[head + i], 0]); right.push([tb.raw[head + j], 0]); i++; j++; kept++;
    } else if (dp[(i + 1) * width + j] >= dp[i * width + (j + 1)]) {
      left.push([ta.raw[head + i], -1]); i++;
    } else {
      right.push([tb.raw[head + j], 1]); j++;
    }
  }
  while (i < m) { left.push([ta.raw[head + i], -1]); i++; }
  while (j < n) { right.push([tb.raw[head + j], 1]); j++; }
  for (let k = 0; k < tail; k++) {
    left.push([ta.raw[A.length - tail + k], 0]);
    right.push([tb.raw[B.length - tail + k], 0]);
  }

  // Two unrelated prompts diff into two solid blocks of highlight, which is
  // noise rather than an answer. Only claim a diff when they're related.
  const similarity = (2 * kept) / (A.length + B.length);
  return { left, right, similarity };
}

function diffSpans(parts) {
  const node = el("div", { className: "wd" });
  let run = "", op = 0;
  const flush = () => {
    if (!run) return;
    node.append(op === 0 ? document.createTextNode(run)
      : el("span", { className: op < 0 ? "del" : "ins" }, run));
    run = "";
  };
  for (const [text, kind] of parts) {
    if (kind !== op) { flush(); op = kind; }
    run += text;
  }
  flush();
  return node;
}

/* Word-level diffing only earns its keep on prose, between exactly two clips. */
const DIFFABLE = /^(prompt|alt_prompt|negative_prompt|activated_loras|loras_multipliers)$/;
let lastDiffWasWordLevel = false;
function valueCells(key, values) {
  if (values.length === 2 && DIFFABLE.test(key) && values[0] !== values[1]
      && (values[0].length > 40 || values[1].length > 40)) {
    // Measured: a re-run with a few words edited scores ~0.99, a rewritten
    // clause ~0.71, two different prompts that merely share WanGP's boilerplate
    // ~0.36. Below the gate, marking up every token is noise, not an answer.
    const diff = wordDiff(values[0], values[1]);
    if (diff && diff.similarity >= 0.45) {
      lastDiffWasWordLevel = true;
      return [diffSpans(diff.left), diffSpans(diff.right)];
    }
  }
  return values.map((value) => {
    const node = el("div", {}, value);
    if (value.length > 200) {
      node.className = "clamp";
      node.title = "Click to expand";
      node.onclick = () => node.classList.toggle("open");
    }
    return node;
  });
}

function diffRows(videos) {
  const metas = videos.map((video) => video.meta || {});
  const allKeys = new Set(metas.flatMap(Object.keys));
  const ordered = [
    ...GROUPS.map(([title, keys]) => [title, keys.filter((key) => allKeys.has(key))]),
    ["Other", [...allKeys].filter((key) => !GROUPED_KEYS.has(key)).sort()],
  ];
  const groups = [];
  for (const [title, keys] of ordered) {
    const rows = [];
    for (const key of keys) {
      if (HIDDEN_KEYS.has(key)) continue;
      const values = metas.map((meta, i) => displayValue(key, meta[key], videos[i]));
      const differs = new Set(values).size > 1;
      if (!state.diffAll && !differs) continue;
      // "All" means all settings that say something, not 30 rows of dashes.
      if (!differs && values.every((value) => value === "—")) continue;
      rows.push({ key, values, differs });
    }
    if (rows.length) groups.push({ title, rows });
  }
  return groups;
}

function buildDiff(videos) {
  const body = el("div");
  const legend = el("div", { className: "wd-legend" }, [
    "in the prompt:", el("i", { className: "del" }, "removed"), el("i", { className: "ins" }, "added"),
  ]);

  const scope = el("div", { className: "segmented", role: "group", ariaLabel: "Which settings to show" });
  const makeScope = (label, all) => {
    const button = el("button", { onclick: () => { state.diffAll = all; build(); } }, label);
    button.setAttribute("aria-pressed", String(state.diffAll === all));
    return button;
  };

  const build = () => {
    scope.replaceChildren(makeScope("Changed", false), makeScope("All", true));
    const groups = diffRows(videos);

    if (!groups.length) {
      legend.hidden = true;
      body.replaceChildren(el("div", { className: "diff-note" },
        "Every setting is identical across the selected clips — the difference is in the sampling, not the recipe."));
      return;
    }
    // The legend only earns its place once something is actually marked up.
    lastDiffWasWordLevel = false;
    const rendered = isMobile() ? diffCards(groups, videos) : diffTable(groups, videos);
    legend.hidden = !lastDiffWasWordLevel;
    body.replaceChildren(rendered);
  };
  build();

  return el("div", { className: "panel", style: "margin-top:12px" }, [
    el("div", { className: "panel-head" }, [
      el("h3", {}, "Settings diff"),
      el("div", { className: "tools" }, [legend, scope]),
    ]),
    body,
  ]);
}

function diffTable(groups, videos) {
  const head = el("thead", {}, el("tr", {}, [
    el("th", {}, "Setting"),
    ...videos.map((video, index) => el("th", { title: video.name }, [
      el("span", { className: "idx" }, String(index + 1)),
      (video.meta || {}).seed != null ? `seed ${video.meta.seed}` : video.name.slice(0, 18),
    ])),
  ]));
  const tbody = el("tbody");
  for (const { title, rows } of groups) {
    tbody.append(el("tr", { className: "group" }, el("td", { colSpan: videos.length + 1 }, title)));
    for (const { key, values, differs } of rows) {
      tbody.append(el("tr", { className: differs ? "differs" : "" }, [
        el("td", { className: "key", title: key }, labelOf(key)),
        ...valueCells(key, values).map((node) => el("td", {}, node)),
      ]));
    }
  }
  return el("div", { className: "diff-wrap" }, el("table", { className: "diff" }, [head, tbody]));
}

function diffCards(groups, videos) {
  const wrap = el("div", { className: "diff-cards" });
  for (const { title, rows } of groups) {
    wrap.append(el("div", { className: "diff-group" }, title));
    for (const { key, values, differs } of rows) {
      const cells = valueCells(key, values);
      wrap.append(el("div", { className: `diff-item${differs ? " differs" : " same"}` }, [
        el("div", { className: "k", title: key }, labelOf(key)),
        ...cells.map((node, index) => el("div", { className: "diff-val" }, [
          el("span", { className: "idx" }, String(index + 1)), node,
        ])),
      ]));
    }
  }
  void videos;
  return wrap;
}

/* ------------------------------------------------------------------ folders */
function renderFolders() {
  const input = el("input", { type: "text", placeholder: "/path/to/another/outputs" });
  const add = async () => {
    const path = input.value.trim();
    if (!path) return;
    try {
      await load("/api/roots/add", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path }),
      });
      input.value = "";
      flash("Folder added");
    } catch (error) { flash(String(error.message || error)); }
  };
  input.onkeydown = (event) => { if (event.key === "Enter") add(); };

  const roots = state.roots.length
    ? state.roots.map((root) => el("div", { className: "root-row" }, [
        icon("folder"),
        el("code", { title: root }, root),
        el("button", {
          className: "sm ghost", onclick: () => load("/api/roots/remove", {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: root }),
          }).catch((error) => flash(String(error))),
        }, "Remove"),
      ]))
    : el("div", { className: "note" }, "No folders indexed yet.");

  $("#view-folders").replaceChildren(el("div", { className: "stack-col" }, [
    panel("Indexed folders", el("div", {}, roots)),
    panel("Add an outputs folder",
      el("div", { style: "display:flex;gap:8px" }, [
        el("div", { style: "flex:1" }, input),
        el("button", { className: "accent", onclick: add }, "Add"),
      ])),
    panel("Compare a file from anywhere", el("div", { style: "display:grid;gap:10px" }, [
      el("div", { className: "dropzone" }, [icon("drop"), "Drop video files anywhere in this window"]),
      el("button", { onclick: () => $("#filePicker").click() }, "Choose a file…"),
    ])),
    panel("How this works", el("div", { className: "note" }, [
      el("p", { style: "margin:0 0 8px" }, [
        "Thumbnails are ", state.ffmpeg ? "on — ffmpeg was found on PATH." : "off — install ffmpeg and rescan to enable them.",
      ]),
      el("p", { style: "margin:0" }, [
        "Settings are read straight out of each MP4's ", el("code", {}, "©cmt"),
        " atom, which WanGP writes when metadata output is enabled. Nothing is copied or modified — the files are only ever read.",
      ]),
    ])),
  ]));
}

/* --------------------------------------------- dropped / picked local files */
const MARKER = [0xA9, 0x63, 0x6D, 0x74]; // "©cmt"

async function readEmbeddedMetadata(file) {
  // WanGP's JSON blob lives in the moov atom, which ffmpeg usually writes at the
  // end of the file (and sometimes at the front). Scan both ends for the tag.
  const span = Math.min(file.size, 8 * 1024 * 1024);
  const chunks = [[0, span]];
  if (file.size > span) chunks.push([file.size - span, file.size]);
  for (const [start, end] of chunks) {
    const bytes = new Uint8Array(await file.slice(start, end).arrayBuffer());
    for (let i = 0; i + 24 < bytes.length; i++) {
      if (bytes[i] !== MARKER[0] || bytes[i + 1] !== MARKER[1] || bytes[i + 2] !== MARKER[2] || bytes[i + 3] !== MARKER[3]) continue;
      const view = new DataView(bytes.buffer, i + 4);
      const dataSize = view.getUint32(0);
      const type = String.fromCharCode(bytes[i + 8], bytes[i + 9], bytes[i + 10], bytes[i + 11]);
      if (type !== "data" || dataSize < 17) continue;
      const payload = bytes.slice(i + 20, Math.min(i + 4 + dataSize, bytes.length));
      try {
        const parsed = JSON.parse(new TextDecoder().decode(payload).replace(/\0+$/, "").trim());
        if (parsed && typeof parsed === "object" && !parsed._wangp_metadata_reserved) return parsed;
      } catch { /* keep scanning */ }
    }
  }
  return {};
}

async function addLocalFiles(files) {
  for (const file of [...files].slice(0, MAX_PICKS)) {
    if (!file.type.startsWith("video/") && !/\.(mp4|mkv|webm|mov|m4v)$/i.test(file.name)) continue;
    const id = `local:${file.name}:${file.size}`;
    if (!state.external.has(id)) {
      const meta = await readEmbeddedMetadata(file);
      const entry = { id, name: file.name, url: URL.createObjectURL(file), size: file.size,
        mtime: file.lastModified / 1000, meta, probe: {}, external: true, path: file.name };
      const probeVideo = document.createElement("video");
      probeVideo.preload = "metadata";
      probeVideo.src = entry.url;
      await new Promise((resolve) => { probeVideo.onloadedmetadata = resolve; probeVideo.onerror = resolve; });
      entry.probe = { duration: probeVideo.duration || 0, width: probeVideo.videoWidth, height: probeVideo.videoHeight };
      state.external.set(id, entry);
    }
    if (!state.picks.includes(id) && state.picks.length < MAX_PICKS) state.picks.push(id);
  }
  setView("compare");
  renderAll();
}

/* ----------------------------------------------------------------- plumbing */
function setView(view) {
  state.view = view;
  if (view !== "preview") state.sheet = true;
  document.body.dataset.view = view;
  document.body.dataset.sheet = (view !== "preview" || state.sheet) ? "1" : "0";
  document.querySelectorAll(".tab").forEach((tab) =>
    tab.setAttribute("aria-selected", String(tab.dataset.view === view)));
  document.querySelectorAll(".tabbar-btn").forEach((tab) =>
    tab.setAttribute("aria-selected", String(tab.dataset.view === view)));
  document.querySelectorAll(".view").forEach((node) =>
    node.classList.toggle("active", node.id === `view-${view}`));
}

function renderAll() {
  const count = state.picks.length;
  const badge = $("#cmpCount");
  badge.textContent = String(count);
  badge.hidden = !count;
  $("#cmpDot").hidden = !count;
  $("#tray").hidden = !count;
  $("#trayCount").textContent = String(count);

  setView(state.view);
  // Emptying the views we're leaving detaches their <video> elements, which
  // both frees the decoders and lets their transport loops fall out of rAF.
  for (const id of ["preview", "compare", "folders"]) {
    if (id !== state.view) $(`#view-${id}`).replaceChildren();
  }
  if (state.view !== "compare") stopCompare();

  renderList();
  if (state.view === "preview") renderPreview();
  else if (state.view === "compare") renderCompare();
  else renderFolders();
}

/* ------------------------------------------------------- sidebar resize/rail */
(function sidebarControls() {
  const resizer = $("#resizer");
  const setWidth = (px) => {
    const width = Math.max(260, Math.min(560, px));
    document.documentElement.style.setProperty("--sidebar-w", `${width}px`);
    try { localStorage.setItem("wvb-sidebar", String(Math.round(width))); } catch (e) { /* ignore */ }
  };
  resizer.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    resizer.setPointerCapture(event.pointerId);
    document.body.classList.add("resizing");
    const onMove = (moveEvent) => setWidth(moveEvent.clientX - $("#sidebar").getBoundingClientRect().left);
    const onUp = () => {
      document.body.classList.remove("resizing");
      resizer.removeEventListener("pointermove", onMove);
      resizer.removeEventListener("pointerup", onUp);
      resizer.removeEventListener("pointercancel", onUp);
    };
    resizer.addEventListener("pointermove", onMove);
    resizer.addEventListener("pointerup", onUp);
    resizer.addEventListener("pointercancel", onUp);
  });
  resizer.addEventListener("keydown", (event) => {
    const current = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--sidebar-w"), 10) || 340;
    if (event.key === "ArrowLeft") { event.preventDefault(); setWidth(current - 16); }
    if (event.key === "ArrowRight") { event.preventDefault(); setWidth(current + 16); }
  });

  $("#railToggle").onclick = () => {
    const collapsed = document.documentElement.dataset.rail === "1";
    if (collapsed) delete document.documentElement.dataset.rail;
    else document.documentElement.dataset.rail = "1";
    try { localStorage.setItem("wvb-rail", collapsed ? "0" : "1"); } catch (e) { /* ignore */ }
    $("#railToggle").setAttribute("aria-label", collapsed ? "Collapse the library panel" : "Show the library panel");
  };
})();

/* --------------------------------------------------------------- listeners */
document.querySelectorAll(".tab, .tabbar-btn").forEach((tab) => {
  tab.onclick = () => {
    if (tab.dataset.view === "preview") state.sheet = false;
    setView(tab.dataset.view);
    renderAll();
  };
});
$("#sheetBack").onclick = () => { state.sheet = false; setView("preview"); };
$("#search").oninput = renderList;
$("#sort").onchange = renderList;

$("#clearPicks").onclick = () => { state.picks = []; renderAll(); };
$("#pickVisible").onclick = () => { state.picks = visibleVideos().slice(0, 2).map((v) => v.id); setView("compare"); renderAll(); };
$("#goCompare").onclick = () => { setView("compare"); renderAll(); };
$("#rescan").onclick = async () => {
  $("#status").textContent = "Rescanning…";
  await load("/api/rescan").catch((error) => flash(String(error)));
};
$("#themeToggle").onclick = () => {
  const root = document.documentElement;
  // With no explicit choice yet, resolve what the system is actually showing
  // and flip away from that.
  const current = root.dataset.theme || "dark"; // dark unless the user chose light
  const next = current === "dark" ? "light" : "dark";
  root.dataset.theme = next;
  try { localStorage.setItem("wvb-theme", next); } catch (e) { /* ignore */ }
};
$("#filePicker").onchange = (event) => addLocalFiles(event.target.files);

document.addEventListener("dragover", (event) => { event.preventDefault(); document.body.classList.add("dragging"); });
document.addEventListener("dragleave", (event) => { if (event.relatedTarget === null) document.body.classList.remove("dragging"); });
document.addEventListener("drop", (event) => {
  event.preventDefault();
  document.body.classList.remove("dragging");
  if (event.dataTransfer.files.length) addLocalFiles(event.dataTransfer.files);
});

document.addEventListener("keydown", (event) => {
  if (/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)) return;
  if (state.view !== "compare" || !cmpTransport) return;
  if (event.key === "b" || event.key === "B") { event.preventDefault(); toggleBlink(); }
  else if (event.code === "Space") { event.preventDefault(); cmpTransport.toggle(); }
  else if (event.key === "ArrowLeft") { event.preventDefault(); cmpTransport.stepFrames(event.shiftKey ? -10 : -1); }
  else if (event.key === "ArrowRight") { event.preventDefault(); cmpTransport.stepFrames(event.shiftKey ? 10 : 1); }
  else if (event.key === "Home") { event.preventDefault(); cmpTransport.seekAll(0); }
});

// The diff and the compare layout are laid out differently per modality, so a
// rotation or a window resize across the breakpoint has to re-render, not reflow.
mq.addEventListener("change", () => renderAll());

$("#list").replaceChildren(el("div", { className: "skeleton", style: "grid-column:1/-1" },
  [el("i"), el("i"), el("i"), el("i"), el("i")]));
setView("preview");
load().catch((error) => { $("#status").textContent = `Error: ${error.message}`; flash(error.message); });
