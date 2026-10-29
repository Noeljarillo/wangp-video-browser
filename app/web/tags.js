/* P4.2 auto-tags as library filters. Vanilla JS, loaded after app.js.

   GET /api/tags returns the vocabulary groups (shot, location, time of day,
   style, camera motion) and each analysed clip's label per group. Every group
   becomes a facet in the sidebar; like the other facets it only appears once
   the analysed clips actually differ on it. Polls while analysis is filling in. */
(function (root) {
  "use strict";

  var POLL_MS = 20000;
  var data = { groups: [], tags: {} };

  function facetFor(group) {
    return {
      key: "auto_" + group.id, label: group.label, all: "Any " + group.label.toLowerCase(), cls: "post",
      values: function (v) { var t = data.tags[v.id]; return t && t[group.id] ? [t[group.id]] : []; },
      show: function (x) { return x.charAt(0).toUpperCase() + x.slice(1); },
    };
  }

  /* Merge the auto-tag facets into app.js's FACETS list (idempotent). */
  function install(facets, body) {
    data = { groups: body.groups || [], tags: body.tags || {} };
    data.groups.forEach(function (g) {
      if (!facets.some(function (f) { return f.key === "auto_" + g.id; })) facets.push(facetFor(g));
    });
    return facets;
  }

  function count() { return Object.keys(data.tags).length; }

  function refresh() {
    return fetch("/api/tags").then(function (r) { return r.json(); }).then(function (body) {
      var before = count();
      if (typeof FACETS === "undefined") return;
      install(FACETS, body);
      if (count() !== before && typeof renderFacets === "function") { renderFacets(); renderList(); }
      var videos = (typeof state !== "undefined" && state.videos) ? state.videos.length : 0;
      if (body.groups && body.groups.length && (!videos || count() < videos)) setTimeout(refresh, POLL_MS);
    }).catch(function () { /* add-on absent: no auto filters */ });
  }

  root.WVB_TAGS = { install: install, facetFor: facetFor, tagsOf: function (id) { return data.tags[id]; } };
  if (typeof document !== "undefined" && typeof fetch === "function") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { setTimeout(refresh, 300); });
    else setTimeout(refresh, 300);
  }
  if (typeof module !== "undefined") module.exports = root.WVB_TAGS;
})(typeof window !== "undefined" ? window : globalThis);
