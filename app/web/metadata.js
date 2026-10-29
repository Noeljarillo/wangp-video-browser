"use strict";

/* ==========================================================================
   Generator metadata: source label in the preview header and a copy button
   for the raw ComfyUI graph. Loaded after app.js and uses its helpers
   (el, icon, copy). Kept in its own file so app.js only needs small hooks.
   ========================================================================== */

const META_SOURCES = {
  wangp: "WanGP",
  comfyui: "ComfyUI",
};

/* Internal keys never shown as settings rows or diffed. */
if (typeof HIDDEN_KEYS !== "undefined") for (const key of ["_source", "_comfy", "_raw"]) HIDDEN_KEYS.add(key);

const metaSourceLabel = (meta) => {
  const source = meta && meta._source;
  if (!source || source === "unknown") return null;
  return META_SOURCES[source] || source.replace(/^./, (c) => c.toUpperCase());
};

/* Raw workflow text for copying: the UI workflow (what ComfyUI loads on paste)
   when present, else the API prompt graph. */
const metaRawWorkflow = (meta) => {
  const raw = meta && meta._comfy;
  if (!raw) return null;
  const graph = raw.workflow || raw.prompt;
  return graph ? JSON.stringify(graph, null, 2) : null;
};

/* Hook: called by renderPreview with the header node it just built. */
function decoratePreviewHead(head, video) {
  const meta = (video && video.meta) || {};
  const label = metaSourceLabel(meta);
  const model = head.querySelector(".preview-model");
  if (label && model) {
    model.prepend(el("span", { className: `meta-source src-${meta._source}`, title: `Settings read from ${label} metadata` }, label));
  }
  const raw = metaRawWorkflow(meta);
  const actions = head.querySelector(".preview-actions");
  if (raw && actions) {
    actions.prepend(el("button", {
      className: "ghost meta-copy-workflow",
      title: "Copy the embedded ComfyUI workflow JSON",
      onclick: () => copy(raw),
    }, [icon("copy"), "Workflow"]));
  }
}

if (typeof module !== "undefined") module.exports = { metaSourceLabel, metaRawWorkflow };
