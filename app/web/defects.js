/* P5.1 defect flags: badges on cards plus one filter facet per flag.

   GET /api/defects lists the flag vocabulary and each analysed clip's flags,
   aesthetic score, jitter and sharpness. Nothing here guesses: a clip without a
   result file simply has no badge. Polls while analysis is still filling in. */
(function (root) {
  "use strict";

  var POLL_MS = 20000;
  var data = { flags: [], clips: {} };
  var badges = [];

  function flagsOf(id) { var c = data.clips[id]; return (c && c.flags) || []; }

  function facetFor(flag) {
    return {
      key: "defect_" + flag.key, label: flag.label, all: "Any " + flag.label.toLowerCase(), cls: "post",
      values: function (v) { return flagsOf(v.id).indexOf(flag.key) >= 0 ? [flag.label] : []; },
      show: function (x) { return x; },
    };
  }

  function install(facets, body) {
    data = { flags: body.flags || [], clips: body.clips || {} };
    badges = data.flags.filter(function (f) { return Object.keys(data.clips).some(function (id) {
      return flagsOf(id).indexOf(f.key) >= 0; }); });
    data.flags.forEach(function (f) {
      if (badges.indexOf(f) < 0) return;                       /* no facet for a flag nothing has */
      if (!facets.some(function (x) { return x.key === "defect_" + f.key; })) facets.push(facetFor(f));
    });
    return facets;
  }

  /* Called from buildCard() right after the filmstrip decorator. */
  function decorateThumb(thumb, video) {
    if (!thumb || !video) return;
    var list = flagsOf(video.id);
    if (!list.length) return;
    var row = document.createElement("span");
    row.className = "defect-badges";
    list.forEach(function (key) {
      var flag = data.flags.filter(function (f) { return f.key === key; })[0];
      if (!flag) return;
      var badge = document.createElement("span");
      badge.className = "defect-badge defect-" + key;
      badge.textContent = flag.label;
      badge.title = flag.hint;
      row.append(badge);
    });
    if (!row.children.length) return;
    var score = data.clips[video.id] && data.clips[video.id].aesthetic;
    if (typeof score === "number") {
      var aes = document.createElement("span");
      aes.className = "defect-aes";
      aes.textContent = "★ " + score.toFixed(1);
      aes.title = "Aesthetic score (LAION predictor, 1-10)";
      row.append(aes);
    }
    thumb.append(row);
  }

  function count() { return Object.keys(data.clips).length; }

  function refresh() {
    return fetch("/api/defects").then(function (r) { return r.json(); }).then(function (body) {
      var before = count(), had = badges.length;
      if (typeof FACETS === "undefined") return;
      install(FACETS, body);
      if (had !== badges.length && typeof renderFacets === "function") { renderFacets(); renderList(); }
      var videos = (typeof state !== "undefined" && state.videos) ? state.videos.length : 0;
      if (body.flags && body.flags.length && (!videos || count() < videos)) setTimeout(refresh, POLL_MS);
      if (count() && count() === before && had === badges.length) return;
    }).catch(function () { /* add-on absent: no defect flags */ });
  }

  root.WVBDefects = { install: install, facetFor: facetFor, decorateThumb: decorateThumb,
    flagsOf: flagsOf, clips: function () { return data.clips; } };
  if (typeof document !== "undefined" && typeof fetch === "function") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { setTimeout(refresh, 400); });
    else setTimeout(refresh, 400);
  }
  if (typeof module !== "undefined") module.exports = root.WVBDefects;
})(typeof window !== "undefined" ? window : globalThis);
