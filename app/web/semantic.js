/* P4.1 semantic ("content") search. Vanilla JS, loaded after app.js.

   The search box keeps its prompt/filename meaning. A Text | Content toggle
   beside it switches to content search (SigLIP frame embeddings in the analysis
   add-on, via GET /api/semantic/search). In Text mode, a query that matches no
   prompt falls back to content search automatically. A content hit opens the
   preview at its best-matching frame. */
(function (root) {
  "use strict";

  var DEBOUNCE = 220;
  var MIN_SCORE = 0.0005; // SigLIP sigmoid probabilities are small; drop near-zero noise
  var state = { mode: "text", cache: {}, pending: null, timer: 0, seekTo: {}, note: null };

  function rank(query) { return state.cache[query.toLowerCase()]; }

  function fetchQuery(query, onDone) {
    var key = query.toLowerCase();
    if (state.cache[key] || state.pending === key) return;
    state.pending = key;
    fetch("/api/semantic/search?q=" + encodeURIComponent(query))
      .then(function (r) { return r.json(); })
      .then(function (body) { state.cache[key] = body; })
      .catch(function () { state.cache[key] = { available: false, reason: "Content search failed.", results: [] }; })
      .then(function () { if (state.pending === key) state.pending = null; onDone(); });
  }

  /* Hook from app.js visibleVideos(): list = facet/hidden-filtered clips,
     textHits = those that also match the prompt text. Returns the list to show
     (ordered by content score) or null to keep the normal text result. */
  function apply(query, list, textHits) {
    var content = state.mode === "content" || (query && !textHits.length && list.length);
    setNote(null);
    if (!query || !content) return null;
    var body = rank(query);
    if (!body) {
      clearTimeout(state.timer);
      state.timer = setTimeout(function () {
        fetchQuery(query, function () { if (typeof renderList === "function") renderList(); });
      }, DEBOUNCE);
      setNote("Searching content\u2026");
      return state.mode === "content" ? [] : null;
    }
    if (!body.available) {
      setNote(body.reason || "Content search unavailable.");
      return state.mode === "content" ? [] : null;
    }
    var byId = {};
    list.forEach(function (v) { byId[v.id] = v; });
    var out = [];
    state.seekTo = {};
    body.results.forEach(function (hit) {
      var v = byId[hit.id];
      if (!v || hit.score < MIN_SCORE) return;
      state.seekTo[v.id] = hit.time;
      out.push(v);
    });
    setNote((state.mode === "content" ? "Content matches" : "No prompt matches \u2014 showing content matches") +
      " (" + out.length + ")");
    return out;
  }

  function setNote(text) {
    if (typeof document === "undefined") return;
    var node = document.getElementById("semNote");
    if (!node) return;
    node.textContent = text || "";
    node.hidden = !text;
  }

  /* Hook from app.js buildPlayer(): open the preview at the matching frame. */
  function seek(media, video) {
    var t = state.seekTo[video.id];
    if (!t) return;
    media.addEventListener("loadedmetadata", function once() {
      media.removeEventListener("loadedmetadata", once);
      media.currentTime = Math.min(t, Math.max(0, (media.duration || t) - 0.05));
    });
  }

  function setMode(mode) {
    state.mode = mode;
    state.cache = {};  // new clips may have been analysed since
    if (typeof document === "undefined") return;
    var input = document.getElementById("search");
    document.querySelectorAll("#semMode button").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.mode === mode));
    });
    if (input) input.placeholder = mode === "content"
      ? "Describe what is on screen: close-up, night, running"
      : "Search prompt, seed, model, filename";
    if (typeof renderList === "function") renderList();
  }

  function mount() {
    var input = document.getElementById("search");
    if (!input || document.getElementById("semMode")) return;
    var field = input.closest(".field");
    var group = document.createElement("div");
    group.id = "semMode";
    group.className = "segmented sem-mode";
    group.setAttribute("role", "group");
    group.setAttribute("aria-label", "Search mode");
    [["text", "Text", "Search prompts, seeds, models and file names"],
     ["content", "Content", "Search what is on screen (analysis add-on)"]].forEach(function (m) {
      var b = document.createElement("button");
      b.type = "button";
      b.dataset.mode = m[0];
      b.textContent = m[1];
      b.title = m[2];
      b.setAttribute("aria-pressed", String(m[0] === state.mode));
      b.onclick = function () { setMode(m[0]); };
      group.appendChild(b);
    });
    var note = document.createElement("div");
    note.id = "semNote";
    note.className = "sem-note";
    note.setAttribute("role", "status");
    note.hidden = true;
    field.insertAdjacentElement("afterend", group);
    group.insertAdjacentElement("afterend", note);
    // Deep link: /?content=night opens the library in content mode with that query.
    var linked = new URLSearchParams(location.search).get("content");
    if (linked) { input.value = linked; setMode("content"); }
  }

  root.WVB_SEM = { apply: apply, seek: seek, setMode: setMode, mode: function () { return state.mode; },
    _state: state };
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
    else mount();
  }
  if (typeof module !== "undefined") module.exports = root.WVB_SEM;
})(typeof window !== "undefined" ? window : globalThis);
