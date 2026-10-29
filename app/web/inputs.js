"use strict";

/* ==========================================================================
   Input references (P1.3): start/end frames, reference images and guide media
   shown as a strip under the player and under each clip in Compare. Loaded
   after app.js and uses its helpers (el, icon, copy). app.js only calls
   WVB_INPUTS.strip(video, { compact }).
   ========================================================================== */

const WVB_INPUTS = (() => {
  const cache = new Map(); // id -> Promise<refs[]>

  const fetchRefs = (video) => {
    if (!cache.has(video.id)) {
      cache.set(video.id, fetch(`/api/inputs/${encodeURIComponent(video.id)}`)
        .then((r) => (r.ok ? r.json() : { inputs: [] }))
        .then((data) => data.inputs || [])
        .catch(() => []));
    }
    return cache.get(video.id);
  };

  const urlOf = (video, ref) => `/input/${encodeURIComponent(video.id)}/${ref.n}`;

  let lastFocus = null;
  function closeLightbox() {
    const box = document.getElementById("inputLightbox");
    if (box) box.remove();
    if (lastFocus) lastFocus.focus();
  }
  function openLightbox(video, ref) {
    closeLightbox();
    lastFocus = document.activeElement;
    const url = urlOf(video, ref);
    const media = ref.kind === "video"
      ? el("video", { src: url, controls: true, autoplay: true, muted: true, loop: true, playsInline: true })
      : el("img", { src: url, alt: `${ref.label}: ${ref.name}` });
    const close = el("button", { className: "ghost", onclick: closeLightbox }, [icon("close"), "Close"]);
    const box = el("div", {
      id: "inputLightbox", className: "in-lightbox", role: "dialog", ariaModal: "true",
      ariaLabel: `${ref.label} ${ref.name}`,
      onclick: (event) => { if (event.target === box) closeLightbox(); },
      onkeydown: (event) => { if (event.key === "Escape") { event.stopPropagation(); closeLightbox(); } },
    }, [
      el("figure", {}, [
        media,
        el("figcaption", {}, [
          el("span", { className: "in-label" }, ref.label),
          el("button", { className: "in-path", title: "Copy recorded path", onclick: () => copy(ref.recorded) }, ref.recorded),
          close,
        ]),
      ]),
    ]);
    document.body.append(box);
    close.focus();
  }

  function tile(video, ref) {
    const title = `${ref.label} · ${ref.recorded}`;
    if (!ref.exists) {
      return el("button", {
        className: "in-tile missing", title: `Not found — click to copy the recorded path\n${ref.recorded}`,
        onclick: () => copy(ref.recorded),
      }, [
        el("span", { className: "in-thumb" }, el("span", { className: "in-nf" }, "not found")),
        el("span", { className: "in-label" }, ref.label),
        el("span", { className: "in-name" }, ref.recorded),
      ]);
    }
    const url = urlOf(video, ref);
    let thumb;
    if (ref.kind === "image") thumb = el("img", { src: url, alt: "", loading: "lazy", decoding: "async" });
    else if (ref.kind === "video") thumb = el("video", { src: url, preload: "metadata", muted: true, playsInline: true });
    else thumb = el("span", { className: "in-nf" }, ref.kind);
    if (ref.kind === "audio") {
      return el("div", { className: "in-tile audio", title }, [
        el("audio", { src: url, controls: true, preload: "none" }),
        el("span", { className: "in-label" }, ref.label),
        el("span", { className: "in-name" }, ref.name),
      ]);
    }
    return el("button", {
      className: "in-tile", title: `${title}\nClick to enlarge`,
      onclick: () => (ref.kind === "file" ? copy(ref.recorded) : openLightbox(video, ref)),
    }, [
      el("span", { className: "in-thumb" }, thumb),
      el("span", { className: "in-label" }, ref.label),
      el("span", { className: "in-name" }, ref.name),
    ]);
  }

  /* A placeholder now, filled when /api/inputs answers. compact = Compare cell. */
  function strip(video, opts = {}) {
    if (!video || video.external) return null;
    const node = el("div", { className: `in-strip${opts.compact ? " compact" : ""}`, ariaLabel: "Input references" });
    node.hidden = true;
    fetchRefs(video).then((refs) => {
      const meta = video.meta || {};
      if (!refs.length) {
        if (opts.compact || meta._source !== "wangp" || !/[IKVFLE]/.test(String(meta.video_prompt_type || "") + String(meta.image_prompt_type || ""))) return;
        node.replaceChildren(el("p", { className: "note in-none" },
          "WanGP did not record this clip's input images. Turn on \"Embed source images\" in WanGP's Config > Outputs and future clips will show them here."));
        node.hidden = false;
        return;
      }
      const found = refs.filter((r) => r.exists).length;
      node.replaceChildren(
        opts.compact ? null : el("div", { className: "in-head" }, [
          el("span", {}, "Inputs"),
          el("span", { className: "in-count" }, found === refs.length ? String(refs.length) : `${found} of ${refs.length} found`),
        ]),
        el("div", { className: "in-row" }, refs.map((ref) => tile(video, ref))),
      );
      node.hidden = false;
    });
    return node;
  }

  return { strip, fetchRefs, _cache: cache };
})();
window.WVB_INPUTS = WVB_INPUTS;
/* The index can arrive before this script runs; redraw once so strips appear. */
if (typeof state !== "undefined" && state.videos && state.videos.length && typeof renderAll === "function") renderAll();
