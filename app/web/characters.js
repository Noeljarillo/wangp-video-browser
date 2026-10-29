/* P3.3 Characters: clustered identities from the analysis add-on.
   GET /api/characters, POST /api/characters/action {op: rename|ignore|merge|split|settings},
   POST /api/characters/recluster. Adds a Characters view, avatars on library cards and a
   character filter on the library list. */
(function (root) {
  "use strict";

  var model = { characters: [], byVideo: {}, settings: {}, installed: false, loaded: false };
  var ui = { filter: null, merge: null, split: null, busy: false, error: "" };

  /* Pure: video id -> visible (not ignored) characters, sorted by name then size. */
  function indexByVideo(characters) {
    var map = {};
    (characters || []).forEach(function (c) {
      if (c.ignored) return;
      c.clips.forEach(function (id) { (map[id] = map[id] || []).push(c); });
    });
    return map;
  }

  function label(c) { return c.name || "Unnamed"; }

  function find(id) {
    for (var i = 0; i < model.characters.length; i++) if (model.characters[i].id === id) return model.characters[i];
    return null;
  }

  /* Pure: does `videoId` pass the active character filter? */
  function passes(filterChar, videoId) {
    return !filterChar || filterChar.clips.indexOf(videoId) >= 0;
  }

  function hidden(video) { return !passes(ui.filter ? find(ui.filter) : null, video.id); }

  function h(tag, props, children) {
    var node = document.createElement(tag);
    Object.keys(props || {}).forEach(function (k) {
      if (k === "on") Object.keys(props.on).forEach(function (e) { node.addEventListener(e, props.on[e]); });
      else if (k in node && k !== "list") node[k] = props[k];
      else node.setAttribute(k, props[k]);
    });
    (children || []).forEach(function (c) {
      if (c == null) return;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }

  function refreshLibrary() {
    if (typeof root.renderList === "function") root.renderList();
    filterBar();
  }

  function load() {
    return fetch("/api/characters").then(function (r) { return r.json(); }).then(function (data) {
      model.characters = data.characters || [];
      model.settings = data.settings || {};
      model.installed = !!data.installed;
      model.byVideo = indexByVideo(model.characters);
      model.loaded = true;
      if (ui.filter && !find(ui.filter)) ui.filter = null;
      if (!model.linked && /[?&]view=characters\b/.test(root.location.search) && typeof root.setView === "function") {
        model.linked = true;  // ?view=characters deep link
        root.setView("characters");
        if (typeof root.renderAll === "function") root.renderAll();
      }
      refreshLibrary();
      if (document.body && document.body.dataset.view === "characters") render();
    }).catch(function () { model.loaded = true; });
  }

  function post(url, body) {
    ui.busy = true;
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || r.status); return j; }); })
      .then(function (j) { ui.error = ""; return j; }, function (e) { ui.error = String(e.message || e); })
      .then(function (j) { ui.busy = false; return load().then(function () { return j; }); });
  }

  function act(body) { return post("/api/characters/action", body); }

  /* ---- library hooks */
  function decorateCard(card, video) {
    var chars = model.byVideo[video.id];
    if (!chars || !chars.length) return;
    var row = h("div", { className: "char-avatars", title: chars.map(label).join(", ") });
    chars.slice(0, 3).forEach(function (c) {
      row.appendChild(h("img", { src: c.avatar, alt: label(c), loading: "lazy", width: 20, height: 20 }));
    });
    if (chars.length > 3) row.appendChild(h("b", {}, ["+" + (chars.length - 3)]));
    card.appendChild(row);
  }

  function filterBar() {
    var list = document.getElementById("list");
    if (!list) return;
    var bar = document.getElementById("charFilter");
    var c = ui.filter ? find(ui.filter) : null;
    if (!c) { if (bar) bar.remove(); return; }
    if (!bar) {
      bar = h("div", { id: "charFilter", className: "char-filter", role: "status" });
      list.parentNode.insertBefore(bar, list);
    }
    bar.replaceChildren(
      h("img", { src: c.avatar, alt: "", width: 20, height: 20 }),
      h("span", {}, ["Character: ", h("b", {}, [label(c)]), " · " + c.count + " clips"]),
      h("button", { type: "button", className: "ghost", on: { click: function () { setFilter(null); } } }, ["Clear"]));
  }

  function setFilter(id) {
    ui.filter = id;
    refreshLibrary();
  }

  /* ---- Characters view */
  function card(c) {
    var merging = ui.merge !== null, selected = merging && ui.merge.indexOf(c.id) >= 0;
    var name = h("input", { type: "text", className: "char-name", value: c.name, placeholder: "Unnamed",
      "aria-label": "Name of character " + label(c), maxLength: 80,
      on: {
        keydown: function (e) { if (e.key === "Enter") e.target.blur(); },
        change: function (e) { act({ op: "rename", id: c.id, name: e.target.value }); },
      } });
    var actions = merging
      ? [h("label", { className: "char-pick" }, [h("input", { type: "checkbox", checked: selected,
          on: { change: function (e) {
            if (e.target.checked) ui.merge.push(c.id); else ui.merge = ui.merge.filter(function (x) { return x !== c.id; });
            render();
          } } }), " Select"])]
      : [
        h("button", { type: "button", className: "ghost", on: { click: function () { setFilter(c.id); if (root.setView) { root.setView("preview"); if (root.renderAll) root.renderAll(); } } } }, ["Show clips"]),
        h("button", { type: "button", className: "ghost", disabled: c.count < 2, title: c.count < 2 ? "Needs at least two clips" : "Move some clips to a new character",
          on: { click: function () { ui.split = { id: c.id, picked: [] }; render(); } } }, ["Split"]),
        h("button", { type: "button", className: "ghost", on: { click: function () { act({ op: "ignore", id: c.id, ignored: !c.ignored }); } } }, [c.ignored ? "Restore" : "Ignore"]),
      ];
    return h("article", { className: "char-card" + (c.ignored ? " ignored" : "") + (selected ? " selected" : "") }, [
      h("img", { className: "char-face", src: c.avatar, alt: "", loading: "lazy" }),
      h("div", { className: "char-body" }, [
        name,
        h("div", { className: "char-meta" }, [c.count + (c.count === 1 ? " clip" : " clips") + (c.modality === "person" ? " · figure" : "")]),
        h("div", { className: "char-actions" }, actions),
      ]),
    ]);
  }

  function splitPanel() {
    var c = find(ui.split.id);
    if (!c) { ui.split = null; return null; }
    var videos = (typeof state !== "undefined" && state.videos) || [];
    var byId = {};
    videos.forEach(function (v) { byId[v.id] = v; });
    return h("section", { className: "char-split", "aria-label": "Split " + label(c) }, [
      h("p", {}, ["Pick the clips of ", h("b", {}, [label(c)]), " that are a different character."]),
      h("div", { className: "char-split-list" }, c.clips.map(function (id) {
        var v = byId[id] || { name: id };
        return h("label", { className: "char-split-item" }, [
          h("input", { type: "checkbox", checked: ui.split.picked.indexOf(id) >= 0, on: { change: function (e) {
            if (e.target.checked) ui.split.picked.push(id); else ui.split.picked = ui.split.picked.filter(function (x) { return x !== id; });
          } } }),
          h("img", { src: "/thumb/" + encodeURIComponent(id), alt: "", loading: "lazy" }),
          h("span", {}, [String(v.name || id)]),
        ]);
      })),
      h("div", { className: "char-actions" }, [
        h("button", { type: "button", className: "accent", on: { click: function () {
          var body = { op: "split", id: c.id, clips: ui.split.picked };
          ui.split = null;
          act(body);
        } } }, ["Split off selected"]),
        h("button", { type: "button", className: "ghost", on: { click: function () { ui.split = null; render(); } } }, ["Cancel"]),
      ]),
    ]);
  }

  function render() {
    var view = document.getElementById("view-characters");
    if (!view) return;
    if (!model.loaded) { load(); return; }
    var visible = model.characters;
    var head = h("div", { className: "char-head" }, [
      h("div", { className: "char-summary" }, [
        !model.installed ? "Characters need the analysis add-on (Install analysis in the Pinokio menu)."
          : visible.length ? visible.length + " characters across the library. Name, merge, split or ignore them; choices survive re-analysis."
          : "No characters yet. They appear once analysis has detected faces or people."]),
      h("label", { className: "char-threshold", title: "How similar a new clip must be to a known character to be auto-assigned (cosine)." }, [
        "Auto-assign at ",
        h("input", { type: "number", min: "0.1", max: "0.95", step: "0.05", value: String(model.settings.assign_face || 0.4),
          "aria-label": "Auto-assign similarity threshold",
          on: { change: function (e) { act({ op: "settings", assign_face: Number(e.target.value) }); } } }),
      ]),
      ui.merge === null
        ? h("button", { type: "button", className: "ghost", disabled: visible.length < 2, on: { click: function () { ui.merge = []; render(); } } }, ["Merge"])
        : h("span", { className: "char-merge-bar" }, [
          h("button", { type: "button", className: "accent", disabled: ui.merge.length < 2, on: { click: function () {
            var ids = ui.merge.slice();
            ui.merge = null;
            act({ op: "merge", id: ids[0], others: ids.slice(1) });
          } } }, ["Merge " + ui.merge.length + " into first"]),
          h("button", { type: "button", className: "ghost", on: { click: function () { ui.merge = null; render(); } } }, ["Cancel"]),
        ]),
      h("button", { type: "button", className: "ghost", disabled: !model.installed, title: "Cluster all detections again",
        on: { click: function () { post("/api/characters/recluster").then(function () { setTimeout(load, 4000); }); } } }, ["Re-cluster"]),
    ]);
    view.replaceChildren(h("div", { className: "chars" }, [
      head,
      ui.error ? h("div", { className: "char-error", role: "alert" }, [ui.error]) : null,
      ui.split ? splitPanel() : null,
      h("div", { className: "char-grid", role: "list" }, visible.map(card)),
    ]));
  }

  if (typeof document !== "undefined" && typeof fetch === "function") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load); else load();
  }

  var api = { indexByVideo: indexByVideo, passes: passes, hidden: hidden, decorateCard: decorateCard,
    render: render, load: load, setFilter: setFilter };
  root.WVB_CHAR = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
