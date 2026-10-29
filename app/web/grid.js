/* WanGP Video Browser - grid view and list virtualisation (P2.1).
   The library list and the grid are one virtual scroller: entries (a card or
   a take group) are packed into rows of `cols` tiles and only the rows near
   the viewport are in the DOM. Row heights are measured once rendered and
   estimated before that, so cards of different heights still scroll smoothly.
   Pure helpers are exported for `node --test tests/grid.test.js`; the DOM part
   runs in the browser as window.WVBGrid. Dev flags: ?mock=5000 (synthetic
   library), ?perf=1 (scripted scroll benchmark with an on-screen result). */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WVBGrid = api.browser();
}(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /* Pack entries into rows. A `span` entry takes a whole row of its own. */
  function layoutRows(entries, cols) {
    const rows = [];
    let buf = [];
    const flush = () => { if (buf.length) rows.push({ key: buf.map((e) => e.key).join("|"), entries: buf, span: false }); buf = []; };
    for (const entry of entries) {
      if (entry.span) { flush(); rows.push({ key: `s:${entry.key}`, entries: [entry], span: true }); continue; }
      buf.push(entry);
      if (buf.length >= cols) flush();
    }
    flush();
    return rows;
  }

  /* offsets[i] = top of row i; offsets[n] = total height. */
  function offsetsOf(rows, heightOf) {
    const out = new Float64Array(rows.length + 1);
    for (let i = 0; i < rows.length; i++) out[i + 1] = out[i] + heightOf(rows[i], i);
    return out;
  }

  /* Index of the row containing y (largest i with offsets[i] <= y). */
  function rowAt(offsets, y) {
    let lo = 0, hi = offsets.length - 2;
    if (hi < 0) return 0;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (offsets[mid] <= y) lo = mid; else hi = mid - 1;
    }
    return lo;
  }

  /* Rows to render for a viewport, with `over` px of overscan each side. */
  function windowOf(offsets, top, height, over) {
    const n = offsets.length - 1;
    if (n <= 0) return [0, 0];
    const start = rowAt(offsets, Math.max(0, top - over));
    const end = Math.min(n, rowAt(offsets, top + height + over) + 1);
    return [start, end];
  }

  /* Synthetic library for ?mock=N: real clips (if any) recycled with unique
     ids, timestamps spread into sessions so the timeline has shape too. */
  function mockVideos(n, base, now) {
    const src = base && base.length ? base : [{ name: "clip.mp4", size: 4e6, meta: {}, probe: { duration: 5, fps: 16 } }];
    const out = [];
    let t = now || 1.7e9;
    let seed = 12345;
    const rnd = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
    for (let i = 0; i < n; i++) {
      const b = src[i % src.length];
      const gen = 30 + Math.round(rnd() * 400);
      t -= rnd() < 0.04 ? 3600 * (2 + rnd() * 20) : gen + rnd() * 90;
      out.push(Object.assign({}, b, {
        id: `mock${i}`, name: `mock_${String(i).padStart(5, "0")}_${b.name}`, mtime: Math.round(t), mock: true,
        meta: Object.assign({}, b.meta || {}, { seed: 1000 + i, generation_time: gen }),
      }));
    }
    return out;
  }

  function browser() {
    const doc = document;
    const LS_LAYOUT = "wvb-layout", LS_COLS = "wvb-cols";
    const get = (k, d) => { try { return localStorage.getItem(k) || d; } catch (e) { return d; } };
    const put = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } };
    const params = new URLSearchParams(location.search);

    let layout = get(LS_LAYOUT, "list") === "grid" ? "grid" : "list";
    let gridCols = Math.max(2, Math.min(6, parseInt(get(LS_COLS, "4"), 10) || 4));
    // ?layout=grid&cols=5 (dev/benchmark override, not persisted)
    if (params.get("layout")) layout = params.get("layout") === "grid" ? "grid" : "list";
    if (params.get("cols")) gridCols = Math.max(2, Math.min(6, parseInt(params.get("cols"), 10) || 4));
    const mobile = matchMedia("(max-width: 767px)");
    const rootEl = doc.documentElement;
    const applyLayoutAttr = () => {
      rootEl.dataset.layout = layout;
      rootEl.style.setProperty("--grid-cols", String(gridCols));
    };
    applyLayoutAttr();

    let list = null, top = null, bottom = null;
    let entries = [], rows = [], offsets = new Float64Array(1), cols = 1;
    const heights = new Map();   // `${layout}:${cols}:${rowKey}` -> px
    let estimate = 90;
    let live = new Map();        // row index -> node
    let range = [0, 0];
    let raf = 0;
    const stats = { updates: 0, built: 0 };

    const colsNow = () => (layout === "grid" ? (mobile.matches ? Math.min(gridCols, 3) : gridCols) : (mobile.matches ? 2 : 1));
    const hKey = (row) => `${layout}:${cols}:${row.key}`;
    const heightOf = (row) => heights.get(hKey(row)) || estimate;

    function ensureMounted() {
      list = doc.getElementById("list");
      if (top && top.parentNode === list) return;
      top = doc.createElement("div"); top.className = "vspace";
      bottom = doc.createElement("div"); bottom.className = "vspace";
      top.setAttribute("aria-hidden", "true"); bottom.setAttribute("aria-hidden", "true");
      list.replaceChildren(top, bottom);
      list.classList.add("vlist");
      live = new Map(); range = [0, 0];
      if (!list.dataset.vbound) {
        list.dataset.vbound = "1";
        list.addEventListener("scroll", schedule, { passive: true });
        addEventListener("resize", () => { relayout(); });
      }
    }

    function schedule() {
      if (raf) return;
      raf = requestAnimationFrame(() => { raf = 0; update(false); });
    }

    function buildRow(row) {
      const node = doc.createElement("div");
      node.className = row.span ? "vrow vrow-span" : "vrow";
      node.setAttribute("role", "presentation");
      for (const entry of row.entries) node.append(entry.build());
      stats.built++;
      return node;
    }

    function recompute() { offsets = offsetsOf(rows, heightOf); }

    function setSpacers() {
      top.style.height = `${offsets[range[0]]}px`;
      bottom.style.height = `${offsets[rows.length] - offsets[range[1]]}px`;
    }

    function update(force) {
      if (!list || !top || top.parentNode !== list) return;
      stats.updates++;
      const [start, end] = windowOf(offsets, list.scrollTop, list.clientHeight || 800, 600);
      if (!force && start === range[0] && end === range[1]) return;
      // Drop rows that left the window, keep the ones still inside (so a
      // hovered tile keeps its scrub video), add the new ones in order.
      for (const [i, node] of live) if (i < start || i >= end || force) { node.remove(); live.delete(i); }
      const fresh = [];
      let anchor = bottom;
      for (let i = end - 1; i >= start; i--) {
        let node = live.get(i);
        if (!node) { node = buildRow(rows[i]); list.insertBefore(node, anchor); live.set(i, node); fresh.push(i); }
        anchor = node;
      }
      range = [start, end];
      // Measure what we just built and correct the estimates.
      let changed = false, sum = 0, count = 0;
      for (const i of fresh) {
        const h = live.get(i).offsetHeight;
        if (!h) continue;
        sum += h; count++;
        if (heights.get(hKey(rows[i])) !== h) { heights.set(hKey(rows[i]), h); changed = true; }
      }
      if (count && heights.size < 64) { const avg = sum / count; if (Math.abs(avg - estimate) > 1) { estimate = avg; changed = true; } }
      if (changed) recompute();
      setSpacers();
    }

    function render(next) {
      ensureMounted();
      entries = next;
      cols = colsNow();
      list.style.setProperty("--cols", String(cols));
      rows = layoutRows(entries, cols);
      if (!heights.size) estimate = layout === "grid" ? 160 : 90;
      recompute();
      if (list.scrollTop > offsets[rows.length]) list.scrollTop = 0;
      update(true);
    }

    function relayout() { if (list && top && top.parentNode === list && colsNow() !== cols) render(entries); }

    function clear() {
      if (list) list.classList.remove("vlist");
      top = bottom = null; entries = []; rows = []; live = new Map();
    }

    const order = () => entries.flatMap((e) => e.ids || []);

    /* Scroll the row holding `id` into the rendered window. */
    function reveal(id) {
      if (!list) return;
      const i = rows.findIndex((r) => r.entries.some((e) => (e.ids || []).includes(id)));
      if (i < 0) return;
      const t = offsets[i], b = offsets[i + 1];
      if (t < list.scrollTop) list.scrollTop = t;
      else if (b > list.scrollTop + list.clientHeight) list.scrollTop = b - list.clientHeight;
      update(false);
    }

    function setLayout(next, colsValue) {
      if (next) layout = next;
      if (colsValue) gridCols = Math.max(2, Math.min(6, colsValue));
      put(LS_LAYOUT, layout); put(LS_COLS, String(gridCols));
      applyLayoutAttr();
      syncTools();
      if (typeof renderList === "function") renderList();
    }

    /* ---- toolbar: List | Grid, column slider */
    let tools = null;
    function syncTools() {
      if (!tools) return;
      tools.querySelectorAll("[data-layout]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.layout === layout)));
      const slider = tools.querySelector("input");
      slider.value = String(gridCols);
      slider.hidden = layout !== "grid";
      slider.setAttribute("aria-valuetext", `${gridCols} columns`);
    }
    function mountTools() {
      const row = doc.querySelector("#sidebar .filter-row");
      if (!row || tools) return;
      tools = doc.createElement("div");
      tools.className = "layout-tools";
      tools.setAttribute("role", "group");
      tools.setAttribute("aria-label", "Library layout");
      const seg = doc.createElement("span");
      seg.className = "segmented";
      tools.append(seg);
      for (const [value, label] of [["list", "List"], ["grid", "Grid"]]) {
        const b = doc.createElement("button");
        b.type = "button"; b.dataset.layout = value; b.textContent = label;
        b.title = `${label} view`;
        b.onclick = () => setLayout(value);
        seg.append(b);
      }
      const slider = doc.createElement("input");
      Object.assign(slider, { type: "range", min: "2", max: "6", step: "1", className: "cols-slider", title: "Grid columns" });
      slider.setAttribute("aria-label", "Grid columns");
      slider.oninput = () => setLayout(null, parseInt(slider.value, 10));
      tools.append(slider);
      row.append(tools);
      syncTools();
    }
    if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", mountTools); else mountTools();
    mobile.addEventListener("change", relayout);

    /* ---- ?mock=N */
    function mockIndex(data) {
      const n = parseInt(params.get("mock") || "", 10);
      if (!n || n < 1) return data;
      return Object.assign({}, data, { videos: mockVideos(Math.min(n, 50000), data.videos || [], Date.now() / 1000) });
    }

    /* ---- ?perf=1: scroll the list top to bottom, frame by frame, and time
       the work each frame does (scroll + virtual update + layout). */
    function perf() {
      if (!params.get("perf")) return;
      let tries = 0;
      const wait = () => {
        if (!rows.length && tries++ < 200) return setTimeout(wait, 50);
        const frames = [], work = [], built0 = stats.built;
        const total = offsets[rows.length] - list.clientHeight;
        const step = Math.max(40, total / 240);
        let last = performance.now();
        const tick = () => {
          const now = performance.now();
          frames.push(now - last); last = now;
          const t0 = performance.now();
          list.scrollTop = Math.min(total, list.scrollTop + step);
          update(false);
          void list.offsetHeight;   // force layout inside the measured work
          work.push(performance.now() - t0);
          if (list.scrollTop < total - 1 && frames.length < 600) requestAnimationFrame(tick);
          else report(frames.slice(1), work, stats.built - built0);
        };
        requestAnimationFrame(tick);
      };
      const pct = (a, p) => { const s = a.slice().sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(p * s.length))] || 0; };
      const report = (frames, work, built) => {
        const result = {
          entries: entries.length, rows: rows.length, frames: frames.length, rowsBuilt: built,
          domRows: list.querySelectorAll(".vrow").length, domCards: list.querySelectorAll(".card").length,
          workP50: +pct(work, 0.5).toFixed(2), workP95: +pct(work, 0.95).toFixed(2), workMax: +Math.max(...work).toFixed(2),
          frameP50: +pct(frames, 0.5).toFixed(2), frameP95: +pct(frames, 0.95).toFixed(2),
          over16ms: work.filter((w) => w > 16.7).length,
        };
        const out = doc.createElement("pre");
        out.id = "perfResult"; out.className = "perf-result";
        out.textContent = `perf ${layout}\n${JSON.stringify(result, null, 1)}`;
        doc.body.append(out);
        doc.body.dataset.perf = JSON.stringify(result);
        console.log(`WVB_PERF ${JSON.stringify(result)}`);
      };
      setTimeout(wait, 100);
    }
    perf();

    return { render, clear, order, reveal, setLayout, mockIndex, layout: () => layout, stats };
  }

  return { layoutRows, offsetsOf, rowAt, windowOf, mockVideos, browser };
}));
