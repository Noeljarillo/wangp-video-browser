/* P3.4 reference consistency and P3.5 identity drift in the UI.

   - a colour-coded score chip on every card (data from /api/consistency)
   - two filter facets: consistency band, and "identity drift" flagged clips
   - a consistency plot under the player: one bar per analysed frame, the reference
     score per input image, and drift frames marked on the same axis
   - a "Consistency" entry in the sort menu, so the best matches come first */
(function (root) {
  "use strict";

  var POLL_MS = 20000;
  var data = { clips: {} };

  function hit(id) { return data.clips[id] || null; }
  function scoreOf(id) { var h = hit(id); return h && typeof h.score === "number" ? h.score : null; }

  function bandClass(score) {
    if (score === null) return "";
    if (score >= 70) return " good";
    if (score >= 40) return " mixed";
    return " poor";
  }

  /* ------------------------------------------------------------- facets */
  function bandFacet(body) {
    return {
      key: "cons_band", label: "Reference match", all: "Any match", cls: "post",
      values: function (v) { var h = hit(v.id); return h && h.band ? [h.band] : []; },
      show: function (x) { return String(x); },
    };
  }

  function driftFacet() {
    return {
      key: "cons_drift", label: "Identity drift", all: "Any", cls: "post",
      values: function (v) { var h = hit(v.id); return h && h.drift ? ["Drifting"] : []; },
      show: function (x) { return x; },
    };
  }

  function install(facets, body) {
    data = { clips: (body && body.clips) || {} };
    var ids = Object.keys(data.clips);
    if (!ids.length) return facets;
    var anyBand = ids.some(function (id) { return data.clips[id].band; });
    var anyDrift = ids.some(function (id) { return data.clips[id].drift; });
    if (anyBand && !facets.some(function (f) { return f.key === "cons_band"; })) facets.push(bandFacet(body));
    if (anyDrift && !facets.some(function (f) { return f.key === "cons_drift"; })) facets.push(driftFacet());
    return facets;
  }

  /* -------------------------------------------------------------- cards */
  function decorateThumb(thumb, video) {
    var h = hit(video.id);
    if (!thumb || !h) return;
    if (h.score === null && !h.drift) return;   /* no references and no drift: nothing to say */
    var chip = document.createElement("span");
    chip.className = "cons-chip" + bandClass(h.score);
    if (h.score === null) {
      chip.textContent = "no ref";
      chip.title = h.note || "No reference images recorded for this clip";
    } else {
      chip.textContent = "match " + Math.round(h.score);
      chip.title = "Reference consistency " + Math.round(h.score) + "/100" +
        (h.refs && h.refs.length ? " across " + h.refs.length + " reference image" + (h.refs.length === 1 ? "" : "s") : "");
    }
    if (h.drift) {
      var mark = document.createElement("span");
      mark.className = "cons-drift";
      mark.textContent = "drift";
      mark.title = "The character changes identity inside this clip";
      chip.append(mark);
    }
    thumb.append(chip);
  }

  /* ------------------------------------------------------------- player */
  var NS = "http://www.w3.org/2000/svg";

  function svg(name, attrs) {
    var node = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    return node;
  }

  function plot(h) {
    var frames = h.frames || [];
    if (frames.length < 2) return null;
    var w = 520, hgt = 64, pad = 4;
    var chart = svg("svg", { viewBox: "0 0 " + w + " " + hgt, class: "cons-plot", role: "img",
      "aria-label": "Reference consistency per frame" });
    var barW = (w - pad * 2) / frames.length;
    var driftFrames = {};
    (h.drift_frames || []).forEach(function (f) { driftFrames[f.frame] = f.cos; });
    frames.forEach(function (frame, i) {
      var v = Math.max(0, Math.min(100, frame.score));
      var barH = (v / 100) * (hgt - pad * 2);
      chart.append(svg("rect", { x: pad + i * barW, y: hgt - pad - barH, width: Math.max(1, barW - 1),
        height: barH, class: "cons-bar" + (driftFrames[frame.frame] !== undefined ? " drift" : "") }));
    });
    chart.append(svg("line", { x1: pad, x2: w - pad, y1: hgt - pad - 0.4 * (hgt - pad * 2),
      y2: hgt - pad - 0.4 * (hgt - pad * 2), class: "cons-threshold" }));
    var tip = svg("title");
    tip.textContent = frames.map(function (f) { return Math.round(f.score); }).join(" / ");
    chart.append(tip);
    return chart;
  }

  function panel(video) {
    var h = hit(video.id);
    if (!h) return null;
    var box = document.createElement("div");
    box.className = "cons-panel";
    var head = document.createElement("div");
    head.className = "cons-head";
    var title = document.createElement("span");
    title.className = "cons-title";
    title.textContent = h.score === null ? "Reference consistency —" : "Reference consistency " + Math.round(h.score) + "/100";
    head.append(title);
    if (h.drift) {
      var warn = document.createElement("span");
      warn.className = "cons-chip poor";
      warn.textContent = "identity drift" + (typeof h.drift_drop === "number" ? " (−" + Math.round(h.drift_drop * 100) + ")" : "");
      warn.title = "The worst frame sits this far from the clip's own median face";
      head.append(warn);
    }
    box.append(head);
    var chart = plot(h);
    if (chart) box.append(chart);
    if (h.refs && h.refs.length) {
      var refs = document.createElement("div");
      refs.className = "cons-refs";
      h.refs.forEach(function (ref) {
        var item = document.createElement("span");
        item.className = "cons-ref";
        item.textContent = ref.name + (ref.score === null ? "" : " · " + Math.round(ref.score));
        item.title = ref.name;
        refs.append(item);
      });
      box.append(refs);
    } else if (h.note) {
      var note = document.createElement("div");
      note.className = "cons-note";
      note.textContent = h.note;
      box.append(note);
    }
    return box;
  }

  /* --------------------------------------------------------------- sort */
  function sortOption() {
    var select = document.getElementById("sort");
    if (!select || select.querySelector('option[value="consistency"]')) return;
    var option = document.createElement("option");
    option.value = "consistency";
    option.textContent = "Best reference match";
    select.append(option);
  }

  root.WVBConsistency = { install: install, decorateThumb: decorateThumb, panel: panel,
    scoreOf: scoreOf, scores: function () { return data.clips; }, sortOption: sortOption };

  if (typeof window !== "undefined" && window.WVB_SORTS === undefined) window.WVB_SORTS = {};
  if (typeof window !== "undefined" && window.WVB_SORTS) {
    window.WVB_SORTS.consistency = function (a, b) {
      var sa = scoreOf(a.id), sb = scoreOf(b.id);
      return (sb === null ? -1 : sb) - (sa === null ? -1 : sa);
    };
  }

  function refresh() {
    return fetch("/api/consistency").then(function (r) { return r.json(); }).then(function (body) {
      if (typeof FACETS === "undefined") return;
      var before = Object.keys(data.clips).length;
      install(FACETS, body);
      sortOption();
      if (typeof renderFacets === "function" && Object.keys(data.clips).length !== before) {
        renderFacets(); renderList();
      }
      var videos = (typeof state !== "undefined" && state.videos) ? state.videos.length : 0;
      if (!videos || Object.keys(data.clips).length < videos) setTimeout(refresh, POLL_MS);
    }).catch(function () { /* add-on absent: no consistency data */ });
  }

  if (typeof document !== "undefined" && typeof fetch === "function") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () { setTimeout(refresh, 500); });
    } else setTimeout(refresh, 500);
  }
  if (typeof module !== "undefined") module.exports = root.WVBConsistency;
})(typeof window !== "undefined" ? window : globalThis);
