/* Live watch folder (P1.5).
   Listens to the server's SSE stream (GET /events) and merges new or removed
   clips into the library without a reload, then says so in a toast. Relies on
   app.js globals (state, flash, renderList, renderFacets, getVideo, titleOf). */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WVBLive = api;
}(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /* Pure merge: returns a new array sorted newest first, deduplicated by id. */
  function merge(videos, added, removed) {
    const drop = new Set(removed || []);
    const byId = new Map();
    for (const v of videos || []) if (!drop.has(v.id)) byId.set(v.id, v);
    const fresh = [];
    for (const v of added || []) {
      if (!v || !v.id || drop.has(v.id)) continue;
      if (!byId.has(v.id)) fresh.push(v);
      byId.set(v.id, v);
    }
    const out = [...byId.values()].sort((a, b) => (b.mtime || 0) - (a.mtime || 0));
    return { videos: out, fresh };
  }

  function label(video) {
    const meta = video.meta || {};
    const prompt = String(meta.prompt || "").trim().split("\n")[0];
    const text = prompt || video.name || "clip";
    return text.length > 60 ? text.slice(0, 57) + "..." : text;
  }

  function toastText(fresh) {
    if (!fresh.length) return "";
    if (fresh.length === 1) return `New render: ${label(fresh[0])}`;
    return `${fresh.length} new renders: ${label(fresh[0])}`;
  }

  function connect() {
    if (typeof EventSource === "undefined" || typeof state === "undefined") return null;
    // ?mock=N replaces the library with synthetic clips; live merging would mix the two.
    if (new URLSearchParams(location.search).get("mock")) return null;
    const source = new EventSource("/events");
    source.onmessage = (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch { return; }
      if (!data || data.type !== "change") return;
      const { videos, fresh } = merge(state.videos, data.added, data.removed);
      const removedAny = (data.removed || []).some((id) => state.videos.some((v) => v.id === id));
      if (!fresh.length && !removedAny) return;
      state.videos = videos;
      state.picks = state.picks.filter((id) => getVideo(id));
      if (!getVideo(state.activeId)) state.activeId = videos.length ? videos[0].id : null;
      const n = videos.length, r = state.roots.length;
      const status = document.getElementById("status");
      if (status) status.textContent = `${n} clip${n === 1 ? "" : "s"} · ${r} folder${r === 1 ? "" : "s"}`;
      renderFacets();
      renderList();
      if (state.view === "timeline" && window.WVBTimeline) WVBTimeline.render();
      if (fresh.length) flash(toastText(fresh));
      document.dispatchEvent(new CustomEvent("wvb:live", { detail: { added: fresh, removed: data.removed || [] } }));
    };
    return source;
  }

  if (typeof document !== "undefined" && typeof window !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", connect);
    else connect();
  }

  return { merge, toastText, label };
}));
