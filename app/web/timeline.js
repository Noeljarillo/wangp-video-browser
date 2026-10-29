/* WanGP Video Browser - session timeline (P2.5).
   Clips laid out by render time and grouped into sessions (a gap of more than
   30 minutes between renders starts a new one), each with render-time bars.
   A render ends at the clip's creation time and started `generation_time`
   seconds earlier. Pure grouping is exported for `node --test
   tests/timeline.test.js`; the view runs in the browser as window.WVBTimeline. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WVBTimeline = api;
}(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const GAP = 30 * 60;

  function spanOf(video) {
    const meta = (video && video.meta) || {};
    const end = Number(meta.creation_timestamp) || Number(video.mtime) || 0;
    const gen = Math.max(0, Number(meta.generation_time) || 0);
    return { video, start: end - gen, end, gen };
  }

  /* Sessions oldest first, clips inside in render order. */
  function sessions(videos, gap = GAP) {
    const spans = (videos || []).map(spanOf).filter((s) => s.end > 0).sort((a, b) => a.start - b.start || a.end - b.end);
    const out = [];
    let cur = null;
    for (const s of spans) {
      if (!cur || s.start - cur.end > gap) { cur = { start: s.start, end: s.end, clips: [], render: 0 }; out.push(cur); }
      cur.clips.push(s);
      cur.end = Math.max(cur.end, s.end);
      cur.render += s.gen;
    }
    return out;
  }

  const fmtDur = (sec) => {
    sec = Math.round(sec);
    if (sec < 60) return `${sec}s`;
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m ${String(s).padStart(2, "0")}s`;
  };

  /* ---- view (browser only; uses app.js globals at call time) */
  function render() {
    const view = document.getElementById("view-timeline");
    if (!view) return;
    const list = sessions(visibleVideos());
    if (!list.length) {
      view.replaceChildren(el("div", { className: "empty" }, [icon("film"),
        el("h3", {}, "No clips to lay out"), el("p", {}, "Clips appear here by the time they were rendered.")]));
      return;
    }
    const clips = list.reduce((n, s) => n + s.clips.length, 0);
    const maxGen = Math.max(1, ...list.flatMap((s) => s.clips.map((c) => c.gen)));
    const day = { weekday: "short", day: "numeric", month: "short" };
    const hm = { hour: "2-digit", minute: "2-digit" };
    const when = (t, o) => new Date(t * 1000).toLocaleString([], o);
    const open = (id) => () => openPreview(id);

    const blocks = list.slice().reverse().map((s, i) => {
      const span = Math.max(1, s.end - s.start);
      const busy = Math.min(100, Math.round((s.render / span) * 100));
      const track = el("div", { className: "tl-track", ariaHidden: "true" }, s.clips.map((c) => {
        const bar = el("button", {
          className: `tl-span${c.video.id === state.activeId ? " active" : ""}`, tabIndex: -1,
          title: `${shortName(c.video, 60)}\n${when(c.start, hm)}–${when(c.end, hm)} · ${fmtDur(c.gen)}`,
          onclick: open(c.video.id),
        });
        bar.style.left = `${((c.start - s.start) / span) * 100}%`;
        bar.style.width = `${(c.gen / span) * 100}%`;
        return bar;
      }));
      const rows = s.clips.slice().reverse().map((c) => {
        const bar = el("i", { className: "tl-bar" });
        bar.style.width = `${(c.gen / maxGen) * 100}%`;
        return el("button", {
          className: `tl-clip${c.video.id === state.activeId ? " active" : ""}`,
          ariaLabel: `${shortName(c.video, 70)}, rendered ${when(c.end, hm)}, took ${fmtDur(c.gen)}`,
          onclick: open(c.video.id),
        }, [
          el("span", { className: "tl-time" }, when(c.end, hm)),
          el("span", { className: "tl-name" }, shortName(c.video, 90)),
          el("span", { className: "tl-gen" }, [el("span", { className: "tl-bar-well" }, bar), el("b", {}, c.gen ? fmtDur(c.gen) : "—")]),
        ]);
      });
      return el("section", { className: "tl-session", ariaLabel: `Session ${list.length - i}` }, [
        el("header", { className: "tl-head" }, [
          el("h3", {}, `${when(s.start, day)} · ${when(s.start, hm)}–${when(s.end, hm)}`),
          el("span", { className: "tl-stats" }, `${s.clips.length} clip${s.clips.length === 1 ? "" : "s"} · ${fmtDur(s.render)} rendering · ${busy}% busy`),
        ]),
        track,
        el("div", { className: "tl-rows", role: "list" }, rows.map((r) => el("div", { role: "listitem" }, r))),
      ]);
    });
    const total = list.reduce((n, s) => n + s.render, 0);
    view.replaceChildren(el("div", { className: "timeline" }, [
      el("div", { className: "tl-summary" }, `${list.length} session${list.length === 1 ? "" : "s"} · ${clips} clips · ${fmtDur(total)} of rendering · new session after 30 min idle`),
      ...blocks,
    ]));
  }

  // ?view=timeline opens straight onto the timeline (deep link).
  if (typeof location !== "undefined" && typeof state !== "undefined" &&
      new URLSearchParams(location.search).get("view") === "timeline") state.view = "timeline";

  return { spanOf, sessions, fmtDur, render, GAP };
}));
