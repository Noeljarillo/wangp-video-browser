/* Filmstrips (P2.2).
   An 8-frame sprite per clip (GET /filmstrip/<id>). The server renders it
   lazily in a queue: 202 means "queued, ask again", 404 means "no ffmpeg or it
   failed" - then the poster simply stays. Cards and grid tiles show the strip
   along the bottom of the thumbnail on hover; the preview shows it under the
   player, and each frame is a button that seeks there. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WVBFilm = api;
}(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const FRAMES = 8;

  /* Pure helpers (unit tested). */
  const frameTimes = (duration, frames = FRAMES) =>
    duration > 0 ? Array.from({ length: frames }, (_, i) => +((i + 0.5) * duration / frames).toFixed(3)) : [];
  const frameAt = (fraction, frames = FRAMES) =>
    Math.max(0, Math.min(frames - 1, Math.floor(fraction * frames)));
  const spritePos = (index, frames = FRAMES) => `${frames > 1 ? (index / (frames - 1)) * 100 : 0}% 0`;
  const clock = (t) => {
    const m = Math.floor(t / 60), s = t - m * 60;
    return `${m}:${s < 10 ? "0" : ""}${s.toFixed(1)}`;
  };

  /* ---- loading: one request per clip, retried while the server queues it */
  const known = new Map();   // id -> Promise<url|null>
  const urlFor = (video) => `/filmstrip/${video.id}?v=${Math.round(video.mtime || 0)}`;
  function load(video) {
    if (!video || video.external) return Promise.resolve(null);
    if (known.has(video.id)) return known.get(video.id);
    const url = urlFor(video);
    const promise = new Promise((resolve) => {
      let tries = 0;
      const attempt = () => fetch(url, { method: "GET" }).then((res) => {
        if (res.status === 200) return resolve(url);
        if (res.status === 202 && tries++ < 60) return setTimeout(attempt, Math.min(4000, 600 + tries * 300));
        resolve(null);   // unavailable: keep the poster
      }).catch(() => resolve(null));
      attempt();
    });
    known.set(video.id, promise);
    promise.then((url) => { if (!url) known.delete(video.id); });
    return promise;
  }

  const make = (tag, className) => { const n = document.createElement(tag); n.className = className; return n; };
  function cells(url, host, tag) {
    const out = [];
    for (let i = 0; i < FRAMES; i++) {
      const cell = make(tag, "fs-cell");
      cell.style.backgroundImage = `url("${url}")`;
      cell.style.backgroundPosition = spritePos(i);
      host.append(cell);
      out.push(cell);
    }
    return out;
  }

  /* ---- cards and grid tiles: strip along the bottom on hover */
  function decorateThumb(thumb, video) {
    if (!thumb || !video || video.external) return;
    let strip = null, list = [];
    const mark = (event) => {
      if (!list.length) return;
      const box = thumb.getBoundingClientRect();
      const i = frameAt((event.clientX - box.left) / Math.max(1, box.width));
      list.forEach((c, k) => c.classList.toggle("on", k === i));
    };
    thumb.addEventListener("pointerenter", (event) => {
      load(video).then((url) => {
        if (!url || !thumb.matches(":hover")) return;
        if (!strip) {
          strip = make("div", "fs-hover");
          strip.setAttribute("aria-hidden", "true");
          list = cells(url, strip, "i");
        }
        thumb.append(strip);
        thumb.classList.add("fs-on");
        mark(event);
      });
    });
    thumb.addEventListener("pointermove", mark);
    thumb.addEventListener("pointerleave", () => { thumb.classList.remove("fs-on"); if (strip) strip.remove(); });
  }

  /* ---- preview: strip under the player, click a frame to seek */
  function previewStrip(player, video) {
    const host = make("div", "fs-strip");
    if (!video || video.external) return host;
    host.setAttribute("role", "group");
    host.setAttribute("aria-label", "Filmstrip");
    host.hidden = true;
    const probe = video.probe || {};
    if (probe.width && probe.height) host.style.setProperty("--fs-ar", `${probe.width} / ${probe.height}`);
    const media = player && player.querySelector("video");
    load(video).then((url) => {
      if (!url) return;   // no ffmpeg: the poster is all there is
      const duration = () => (media && isFinite(media.duration) && media.duration) ||
        ((video.probe || {}).duration) || 0;
      const buttons = cells(url, host, "button");
      buttons.forEach((b, i) => {
        b.type = "button";
        const label = () => { const t = frameTimes(duration())[i]; return t != null ? `Seek to ${clock(t)}` : `Frame ${i + 1}`; };
        b.title = label();
        b.setAttribute("aria-label", label());
        b.addEventListener("click", () => {
          const t = frameTimes(duration())[i];
          if (media && t != null) { media.currentTime = t; b.title = label(); }
        });
      });
      const sync = () => {
        const d = duration();
        const i = d ? frameAt(media.currentTime / d) : -1;
        buttons.forEach((b, k) => b.classList.toggle("on", k === i));
      };
      if (media) { media.addEventListener("timeupdate", sync); media.addEventListener("seeked", sync); }
      host.hidden = false;
    });
    return host;
  }

  return { frameTimes, frameAt, spritePos, clock, load, decorateThumb, previewStrip, FRAMES };
}));
