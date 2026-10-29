/* P5.2 "What works for me": charts of what the library says about settings.

   Everything is read-only and computed in the browser from data the app already
   has (clip metadata + library ratings) plus /api/defects (aesthetic, jitter) and
   /api/consistency when the analysis add-on has produced it. Plain inline SVG,
   no chart library (C1). Every chart carries a one-line plain-language takeaway,
   and a chart with too few rated clips says so instead of inventing a trend. */
(function (root) {
  "use strict";

  var MIN_CLIPS = 3;         /* below this a bucket is noise, not a finding */
  var MIN_RATED = 3;         /* charts need at least this many rated clips */

  var SERIES = [
    { key: "num_inference_steps", label: "Steps", kind: "num", meta: true },
    { key: "guidance_scale", label: "Guidance", kind: "num", meta: true },
    { key: "shift", label: "Shift", kind: "num", meta: true },
    { key: "lora_weight", label: "LoRA weight", kind: "num", meta: true },
    { key: "model_type", label: "Model", kind: "cat", meta: true },
    { key: "resolution", label: "Resolution", kind: "cat", meta: true },
    { key: "aesthetic", label: "Aesthetic score", kind: "num", defects: true },
    { key: "consistency", label: "Reference consistency", kind: "num", consistency: true },
  ];

  function num(v) { var n = parseFloat(v); return isFinite(n) ? n : null; }

  function metaValue(video, key) {
    var meta = video.meta || {};
    if (key === "shift") {
      for (var k of ["shift", "sample_shift", "flow_shift", "sample_shift_scaler"]) {
        var n = num(meta[k]); if (n !== null) return n;
      }
      return null;
    }
    if (key === "lora_weight") {
      var m = meta.loras_multipliers || meta.activated_loras;
      if (Array.isArray(m)) {
        var vals = m.map(function (x) { return Math.abs(num(x) || 0); }).filter(function (x) { return x > 0; });
        return vals.length ? Math.max.apply(null, vals) : null;
      }
      var s = String(m || "").split(/[;, ]+/).map(num).filter(function (x) { return x !== null && x !== 0; });
      return s.length ? Math.max.apply(null, s.map(Math.abs)) : null;
    }
    if (key === "model_type") return meta.model_type || meta.model || null;
    if (key === "resolution") {
      var r = meta.resolution;
      if (Array.isArray(r)) return r.join("x");
      return r || null;
    }
    return num(meta[key]);
  }

  function seriesFor(video, series, extra) {
    if (series.defects) return ((extra.defects || {})[video.id] || {}).aesthetic ?? null;
    if (series.consistency) return ((extra.consistency || {})[video.id] || {}).score ?? null;
    return metaValue(video, series.key);
  }

  function ratingOf(video) { return (video.lib || {}).rating || 0; }

  function rowsFor(series, videos, extra) {
    var rows = [];
    videos.forEach(function (v) {
      var x = seriesFor(v, series, extra);
      if (x === null || x === undefined || x === "") return;
      rows.push({ video: v, x: x, rating: ratingOf(v), status: (v.lib || {}).status || null });
    });
    return rows;
  }

  /* Numeric axis -> buckets of neighbouring values, so 8/12/20 steps stay separate
     but a 0.1-wide guidance range does not produce 40 empty columns. */
  var MAX_BINS = 8;   /* more columns than this and the axis labels collide */

  function bucketRows(groups) {
    groups.forEach(function (b) {
      var rs = b.rows;
      b.n = rs.length;
      b.rated = rs.filter(function (r) { return r.rating; }).length;
      b.mean = rs.length ? rs.reduce(function (a, r) { return a + r.rating; }, 0) / rs.length : 0;
      b.meanRated = b.rated ? rs.reduce(function (a, r) { return a + r.rating; }, 0) / b.rated : 0;
      b.keeps = rs.filter(function (r) { return r.status === "keep"; }).length;
      b.rejects = rs.filter(function (r) { return r.status === "reject"; }).length;
    });
    return groups.sort(function (a, b) { return a.x - b.x; });
  }

  function buckets(rows) {
    var map = new Map();
    rows.forEach(function (r) { if (!map.has(r.x)) map.set(r.x, []); map.get(r.x).push(r); });
    var exact = Array.from(map, function (entry) { return { x: entry[0], rows: entry[1] }; })
      .sort(function (a, b) { return a.x - b.x; });
    if (exact.length <= MAX_BINS) {
      return bucketRows(exact.map(function (b) { return { x: b.x, rows: b.rows, label: String(b.x) }; }));
    }
    /* Wide numeric range (an aesthetic score has dozens of values): equal-width bins, so
       the axis stays readable and the takeaway still names a range, not a fake value. */
    var xs = exact.map(function (b) { return b.x; });
    var lo = xs[0], hi = xs[xs.length - 1];
    var step = (hi - lo) / MAX_BINS || 1;
    var bins = [];
    for (var i = 0; i < MAX_BINS; i += 1) {
      var from = lo + i * step, to = i === MAX_BINS - 1 ? hi : lo + (i + 1) * step;
      var rs = rows.filter(function (r) { return r.x >= from && (i === MAX_BINS - 1 ? r.x <= to : r.x < to); });
      if (!rs.length) continue;
      bins.push({ x: Math.round(from * 100) / 100, rows: rs,
        label: (Math.round(from * 10) / 10) + "–" + (Math.round(to * 10) / 10) });
    }
    return bucketRows(bins);
  }

  function catBuckets(rows) {
    var map = {};
    rows.forEach(function (r) { (map[r.x] = map[r.x] || []).push(r); });
    return Object.keys(map).map(function (k) {
      var rs = map[k];
      var rated = rs.filter(function (r) { return r.rating; });
      return { x: k, n: rs.length, rated: rated.length,
        meanRated: rated.length ? rated.reduce(function (a, r) { return a + r.rating; }, 0) / rated.length : 0,
        keeps: rs.filter(function (r) { return r.status === "keep"; }).length,
        rejects: rs.filter(function (r) { return r.status === "reject"; }).length };
    }).sort(function (a, b) { return b.meanRated - a.meanRated; });
  }

  function takeaway(series, groups, ratedTotal) {
    if (ratedTotal < MIN_RATED) return null;   /* nothing honest to say yet */
    var usable = groups.filter(function (g) { return g.rated >= 2 && g.n >= 1; });
    if (usable.length < 2) return "Only one " + series.label.toLowerCase() + " value has rated clips so far.";
    var best = groups.slice().sort(function (a, b) { return b.meanRated - a.meanRated; })[0];
    var worst = groups.slice().sort(function (a, b) { return a.meanRated - b.meanRated; })[0];
    if (Math.abs(best.meanRated - worst.meanRated) < 0.25) {
      return series.label + " makes no clear difference on this library yet (" +
        best.meanRated.toFixed(1) + " vs " + worst.meanRated.toFixed(1) + " stars).";
    }
    var at = best.label || best.x;
    var verb = series.kind === "num" ? "scores best at " + at : "scores best";
    return series.label + " " + verb + " — " + best.meanRated.toFixed(1) + " stars over " + best.rated +
      " rated clip" + (best.rated === 1 ? "" : "s") + ", against " + worst.meanRated.toFixed(1) +
      " for " + (worst.label || worst.x) + ".";
  }

  /* ------------------------------------------------------------------ svg */
  var NS = "http://www.w3.org/2000/svg";

  function svgEl(name, attrs) {
    var node = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    return node;
  }

  function barChart(groups, opts) {
    var w = 460, h = 150, pad = { l: 26, r: 8, t: 10, b: 30 };
    var svg = svgEl("svg", { viewBox: "0 0 " + w + " " + h, class: "ins-chart", role: "img",
      "aria-label": opts.label + " against average rating" });
    var innerW = w - pad.l - pad.r, innerH = h - pad.t - pad.b;
    [1, 3, 5].forEach(function (v) {
      var y = pad.t + innerH - (v / 5) * innerH;
      svg.append(svgEl("line", { x1: pad.l, x2: w - pad.r, y1: y, y2: y, class: "ins-rule" }));
      var t = svgEl("text", { x: pad.l - 6, y: y + 3, class: "ins-axis", "text-anchor": "end" });
      t.textContent = String(v);
      svg.append(t);
    });
    /* Categorical values are long model or resolution names: shorten them, and if two
       shortenings collide fall back to the tail, which is what usually differs. */
    var shorts = groups.map(function (g) { return String(g.label || g.x); }).map(function (s) {
      return s.length > 10 ? s.slice(0, 9) + "…" : s;
    });
    var seen = {};
    shorts.forEach(function (s) { seen[s] = (seen[s] || 0) + 1; });
    shorts = shorts.map(function (s, i) {
      if (seen[s] < 2) return s;
      var full = String(groups[i].label || groups[i].x);
      return "…" + full.slice(-8);
    });
    opts.short = shorts;
    var slot = innerW / Math.max(1, groups.length);
    groups.forEach(function (g, i) {
      var bw = Math.min(38, slot * 0.62);
      var x = pad.l + i * slot + (slot - bw) / 2;
      var barH = (g.meanRated / 5) * innerH;
      var y = pad.t + innerH - barH;
      var bar = svgEl("rect", { x: x, y: y, width: bw, height: Math.max(1, barH), rx: 2,
        class: "ins-bar" + (g.keeps ? " kept" : g.rejects ? " rejected" : "") });
      var tip = svgEl("title");   // append() returns undefined, so the text goes on first
      tip.textContent = g.rated + " rated · " + g.n + " clips · " + g.meanRated.toFixed(2) + " avg";
      bar.append(tip);
      svg.append(bar);
      var label = svgEl("text", { x: x + bw / 2, y: h - pad.b + 13, class: "ins-axis", "text-anchor": "middle" });
      label.textContent = opts.short ? opts.short[i] : String(g.label || g.x);
      svg.append(label);
      var n = svgEl("text", { x: x + bw / 2, y: h - pad.b + 24, class: "ins-note", "text-anchor": "middle" });
      n.textContent = g.n + " clip" + (g.n === 1 ? "" : "s");
      svg.append(n);
    });
    return svg;
  }

  /* ----------------------------------------------------------------- view */
  function render(host, videos, extra) {
    host.replaceChildren();
    var head = document.createElement("div");
    head.className = "ins-head";
    head.innerHTML = "";
    var h2 = document.createElement("h2");
    h2.textContent = "What works for me";
    var p = document.createElement("p");
    var rated = videos.filter(function (v) { return ratingOf(v); }).length;
    p.textContent = rated + " of " + videos.length + " clips are rated. Rate clips with the " +
      "number keys (1–5) and these charts fill in.";
    head.append(h2, p);
    host.append(head);

    var grid = document.createElement("div");
    grid.className = "ins-grid";
    var shown = 0;
    SERIES.forEach(function (series) {
      var rows = rowsFor(series, videos, extra);
      if (rows.length < MIN_CLIPS) return;
      var groups = series.kind === "num" ? buckets(rows) : catBuckets(rows);
      if (groups.length < 2) return;
      var card = document.createElement("section");
      card.className = "ins-card";
      var title = document.createElement("h3");
      title.textContent = series.label;
      card.append(title, barChart(groups, { label: series.label }));
      var note = document.createElement("p");
      var text = takeaway(series, groups, rows.filter(function (r) { return r.rating; }).length);
      note.className = "ins-take" + (text ? "" : " ins-empty");
      note.textContent = text || "Not enough rated clips at different " + series.label.toLowerCase() +
        " values yet.";
      card.append(note);
      grid.append(card);
      shown += 1;
    });
    if (!shown) {
      var empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "Nothing to chart yet: clips need settings metadata and ratings.";
      grid.append(empty);
    }
    host.append(grid);
  }

  function collect() {
    var videos = (typeof state !== "undefined" && state.videos) ? state.videos : [];
    var extra = { defects: {}, consistency: {} };
    if (root.WVBDefects) extra.defects = root.WVBDefects.clips() || {};
    if (root.WVBConsistency) extra.consistency = root.WVBConsistency.scores() || {};
    return { videos: videos, extra: extra };
  }

  var deepLinked = false;

  function renderView() {
    var host = document.getElementById("view-insights");
    if (!host) return;
    var data = collect();
    var paint = function (body) {
      if (body && body.clips) data.extra.defects = body.clips;
      render(host, data.videos, data.extra);
    };
    /* The view is drawn from two sources: the library payload the app already has and
       the defect results, so it asks for the latter once and then paints. */
    /* ?view=insights deep link, same as the Characters view. Fired straight away so it
       does not depend on the defect fetch succeeding. */
    if (!deepLinked && root.location && /[?&]view=insights\b/.test(root.location.search) &&
        typeof root.setView === "function") {
      deepLinked = true;
      root.setView("insights");
      if (typeof root.renderAll === "function") root.renderAll();
    }
    fetch("/api/defects").then(function (r) { return r.json(); }).then(paint)
      .catch(function () { paint(null); });
  }

  root.WVBInsights = { render: renderView, view: render, rowsFor: rowsFor,
    buckets: buckets, catBuckets: catBuckets,
    takeaway: takeaway, metaValue: metaValue };
  /* ?view=insights deep link. It has to live here, like the Characters and Timeline
     views, because renderAll only draws a view that is already the current one. */
  function boot() {
    if (typeof root.setView !== "function") return;
    root.setView("insights");
    if (typeof root.renderAll === "function") root.renderAll();
  }
  if (typeof document !== "undefined" && root.location &&
      /[?&]view=insights\b/.test(root.location.search)) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { setTimeout(boot, 350); });
    else setTimeout(boot, 350);
  }
  if (typeof module !== "undefined") module.exports = root.WVBInsights;
})(typeof window !== "undefined" ? window : globalThis);
