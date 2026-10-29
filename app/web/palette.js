/* Command palette (P6.2).
   Ctrl/Cmd+K opens a palette: jump to a clip, apply a filter, switch view or
   layout, run an action on the active clip. "?" opens an overlay listing every
   keyboard shortcut. Pure helpers (fuzzyScore, rank, SHORTCUTS) are exported
   for node --test; the UI part only runs in the browser and uses app.js
   globals (state, getVideo, setView, renderAll, ...). */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WVB_PALETTE = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /* Subsequence fuzzy match. Returns -1 for no match, else a score where
     higher is better: contiguous runs, word starts and early hits win. */
  function fuzzyScore(query, text) {
    const q = String(query || "").toLowerCase().trim();
    const t = String(text || "").toLowerCase();
    if (!q) return 0;
    const sub = t.indexOf(q);
    if (sub >= 0) return 1000 - Math.min(sub, 500) + (sub === 0 || /\W/.test(t[sub - 1]) ? 200 : 0);
    let score = 0, ti = 0, run = 0;
    for (const ch of q) {
      if (ch === " ") { run = 0; continue; }
      const at = t.indexOf(ch, ti);
      if (at < 0) return -1;
      run = at === ti ? run + 1 : 0;
      score += 1 + run * 3 + (at === 0 || /\W/.test(t[at - 1]) ? 5 : 0) - Math.min((at - ti) * 0.1, 3);
      ti = at + 1;
    }
    return score;
  }

  /* items: [{label, hint?, keywords?}] -> best-first, at most `limit`. */
  function rank(items, query, limit = 50) {
    if (!String(query || "").trim()) return items.slice(0, limit);
    const scored = [];
    items.forEach((item, i) => {
      const a = fuzzyScore(query, item.label);
      const b = item.keywords ? fuzzyScore(query, item.keywords) - 50 : -1;
      const s = Math.max(a, b);
      if (s >= 0) scored.push([s, i, item]);
    });
    scored.sort((x, y) => y[0] - x[0] || x[1] - y[1]);
    return scored.slice(0, limit).map((x) => x[2]);
  }

  /* Every shortcut in the app (collected from the keydown handlers in app.js,
     library.js, inputs.js and this file). */
  const SHORTCUTS = [
    ["Anywhere", [
      ["Ctrl/Cmd+K", "Open the command palette"],
      ["?", "Show this shortcut list"],
      ["Esc", "Close palette, overlay or lightbox"],
    ]],
    ["Library", [
      ["Up / Down / J", "Previous / next clip"],
      ["Enter / Space", "Open the focused clip"],
      ["Double-click", "Add or remove a clip from Compare"],
      ["1 - 5", "Rate the clip (same key again clears)"],
      ["0", "Clear the rating"],
      ["K", "Keep and advance"],
      ["X", "Reject and advance"],
      ["T", "Add tags"],
      ["C", "Add to a collection"],
      ["G", "Group takes on or off"],
    ]],
    ["Player", [
      ["Left / Right", "Step one frame (on the timeline)"],
      ["Shift+Left / Right", "Step ten frames"],
    ]],
    ["Compare", [
      ["Space", "Play or pause all"],
      ["Left / Right", "Step one frame (Shift: ten)"],
      ["Home", "Back to the start"],
      ["B", "Blink between clips"],
      ["Left / Right on wipe", "Move the wipe divider (Shift: faster)"],
      ["Home / End on wipe", "Wipe fully left / right"],
    ]],
    ["Sidebar", [
      ["Left / Right on divider", "Resize the library panel"],
    ]],
  ];

  if (typeof document === "undefined") return { fuzzyScore, rank, SHORTCUTS };

  /* ---------------------------------------------------------------- browser */
  const h = (tag, props, kids) => el(tag, props || {}, kids || []);
  let box = null, input = null, listEl = null, items = [], shown = [], sel = 0, lastFocus = null;

  const clipLabel = (v) => {
    const m = v.meta || {};
    const prompt = String(m.prompt || "").replace(/\s+/g, " ").slice(0, 80);
    return { label: v.name, hint: prompt, keywords: `${prompt} ${m.seed != null ? `seed ${m.seed}` : ""}` };
  };

  function commands() {
    const out = [];
    const cmd = (group, label, run, extra) => out.push(Object.assign({ group, label, run }, extra || {}));
    const active = state.activeId && getVideo(state.activeId);
    for (const [view, name] of [["preview", "Preview"], ["compare", "Compare"], ["folders", "Folders"], ["timeline", "Timeline"]]) {
      cmd("View", `Go to ${name}`, () => { const tab = document.querySelector(`.tab[data-view="${view}"]`); if (tab) tab.click(); else { setView(view); renderAll(); } });
    }
    for (const layout of ["list", "grid"]) {
      cmd("View", `Library as ${layout === "list" ? "list" : "grid"}`, () => {
        const b = document.querySelector(`.layout-tools button[data-layout="${layout}"]`);
        if (b) b.click();
      });
    }
    if (active && !active.external && window.WVB_LIB && WVB_LIB.setRating) {
      for (let n = 1; n <= 5; n++) cmd("Action", `Rate ${n} star${n > 1 ? "s" : ""}`, () => WVB_LIB.setRating(active.id, n), { keys: String(n) });
      cmd("Action", "Clear rating", () => WVB_LIB.setRating(active.id, 0), { keys: "0" });
      cmd("Action", "Keep clip", () => WVB_LIB.setStatus(active.id, "keep", true), { keys: "K" });
      cmd("Action", "Reject clip", () => WVB_LIB.setStatus(active.id, "reject", true), { keys: "X" });
    }
    if (active) {
      const picked = state.picks.includes(active.id);
      cmd("Action", picked ? "Remove clip from Compare" : "Add clip to Compare", () => togglePick(active.id));
      if (window.WVB_EXPORT && WVB_EXPORT.download && (!WVB_EXPORT.exportable || WVB_EXPORT.exportable(active))) {
        cmd("Action", "Export settings for WanGP", () => WVB_EXPORT.download(active, false));
        cmd("Action", "Export settings with a new seed", () => WVB_EXPORT.download(active, true));
      }
    }
    if (state.picks.length) cmd("Action", "Clear Compare", () => { state.picks.length = 0; renderAll(); });
    if (window.WVB_EXPORT_CMP && state.picks.length >= 2) {
      cmd("Action", "Export comparison video", () => { const t = document.querySelector('.tab[data-view="compare"]'); if (t) t.click(); WVB_EXPORT_CMP.open(); });
    }
    if (window.WVB_LIB && WVB_LIB.setGroupMode) cmd("Action", "Toggle group takes", () => { const g = document.getElementById("libGroupTakes"); if (g) g.click(); }, { keys: "G" });
    const rej = document.getElementById("libShowRejects");
    if (rej) cmd("Filter", rej.checked ? "Hide rejects" : "Show rejects", () => rej.click());
    if (typeof FACETS !== "undefined" && state.facets) {
      for (const f of FACETS) {
        const values = new Set();
        for (const v of state.videos) for (const x of f.values(v)) values.add(x);
        for (const value of values) {
          cmd("Filter", `${f.label}: ${f.show ? f.show(value) : value}`, () => {
            state.facets[f.key] = value; renderFacets(); renderList();
          });
        }
      }
      if (Object.values(state.facets).some(Boolean)) cmd("Filter", "Clear filters", () => { state.facets = {}; renderFacets(); renderList(); });
    }
    cmd("Help", "Keyboard shortcuts", () => openHelp(), { keys: "?" });
    for (const v of state.videos) out.push(Object.assign({ group: "Clip", run: () => openPreview(v.id) }, clipLabel(v)));
    return out;
  }

  function render() {
    shown = rank(items, input.value, 60);
    sel = Math.min(sel, Math.max(0, shown.length - 1));
    listEl.replaceChildren(...(shown.length ? shown.map((item, i) => h("li", {
      className: "pal-item", role: "option", id: `pal-${i}`, ariaSelected: String(i === sel),
      onmousedown: (e) => { e.preventDefault(); choose(i); },
      onmousemove: () => { if (sel !== i) { sel = i; mark(); } },
    }, [
      h("span", { className: "pal-group" }, item.group),
      h("span", { className: "pal-label" }, item.label),
      item.hint ? h("span", { className: "pal-hint" }, item.hint) : null,
      item.keys ? h("kbd", {}, item.keys) : null,
    ])) : [h("li", { className: "pal-empty" }, "No matches")]));
    mark();
  }
  function mark() {
    listEl.querySelectorAll(".pal-item").forEach((n, i) => n.setAttribute("aria-selected", String(i === sel)));
    const cur = listEl.children[sel];
    if (cur && cur.classList.contains("pal-item")) { input.setAttribute("aria-activedescendant", cur.id); cur.scrollIntoView({ block: "nearest" }); }
  }
  function choose(i) {
    const item = shown[i];
    close();
    if (item) item.run();
  }

  function open() {
    if (box) return;
    lastFocus = document.activeElement;
    items = commands();
    sel = 0;
    input = h("input", { type: "text", className: "pal-input", placeholder: "Jump to a clip, filter, view or action", ariaLabel: "Command",
      role: "combobox", ariaExpanded: "true", ariaControls: "palList", autocomplete: "off", spellcheck: false });
    listEl = h("ul", { className: "pal-list", id: "palList", role: "listbox", ariaLabel: "Results" });
    input.oninput = () => { sel = 0; render(); };
    input.onkeydown = (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); sel = Math.min(sel + 1, shown.length - 1); mark(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); sel = Math.max(sel - 1, 0); mark(); }
      else if (e.key === "Enter") { e.preventDefault(); choose(sel); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
      else if (e.key === "Tab") e.preventDefault();
    };
    box = h("div", { className: "pal-scrim", onmousedown: (e) => { if (e.target === box) close(); } }, [
      h("div", { className: "pal", role: "dialog", ariaModal: "true", ariaLabel: "Command palette" }, [input, listEl,
        h("div", { className: "pal-foot" }, [h("kbd", {}, "Up/Down"), " move  ", h("kbd", {}, "Enter"), " run  ", h("kbd", {}, "Esc"), " close  ", h("kbd", {}, "?"), " shortcuts"])]),
    ]);
    document.body.append(box);
    render();
    input.focus();
  }
  function close() {
    if (!box) return;
    box.remove();
    box = null;
    if (lastFocus && lastFocus.isConnected && lastFocus.focus) lastFocus.focus();
  }

  let help = null;
  function openHelp() {
    if (help) return;
    const prev = document.activeElement;
    const closeHelp = () => { help.remove(); help = null; if (prev && prev.isConnected && prev.focus) prev.focus(); };
    const btn = h("button", { className: "link pal-close", onclick: closeHelp }, "Close");
    help = h("div", { className: "pal-scrim", onmousedown: (e) => { if (e.target === help) closeHelp(); },
      onkeydown: (e) => { if (e.key === "Escape" || e.key === "?") { e.preventDefault(); e.stopPropagation(); closeHelp(); } } }, [
      h("div", { className: "pal pal-help", role: "dialog", ariaModal: "true", ariaLabel: "Keyboard shortcuts", tabIndex: -1 }, [
        h("div", { className: "pal-help-head" }, [h("h2", {}, "Keyboard shortcuts"), btn]),
        h("div", { className: "pal-help-body" }, SHORTCUTS.map(([group, rows]) => h("section", {}, [
          h("h3", {}, group),
          h("dl", {}, rows.flatMap(([k, d]) => [h("dt", {}, h("kbd", {}, k)), h("dd", {}, d)])),
        ]))),
      ]),
    ]);
    document.body.append(help);
    btn.focus();
  }

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      if (box) close(); else open();
      return;
    }
    if (e.key === "?" && !e.ctrlKey && !e.metaKey && !e.altKey && !box && !help &&
        !/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName) && !document.activeElement.isContentEditable) {
      e.preventDefault();
      openHelp();
    }
  });

  // A visible entry point (touch devices have no Ctrl+K).
  const theme = document.getElementById("themeToggle");
  if (theme) {
    const mac = /Mac|iPhone|iPad/.test(navigator.platform || "");
    theme.before(h("button", { className: "ghost pal-open", type: "button", title: "Command palette", ariaLabel: "Open the command palette",
      onclick: open }, [h("span", { className: "pal-open-text" }, "Commands"), h("kbd", { className: "only-desktop" }, mac ? "Cmd K" : "Ctrl K")]));
  }

  // Dev/screenshot flag: ?palette=open | ?palette=help (like grid.js ?layout=).
  const flag = new URLSearchParams(location.search).get("palette");
  if (flag) setTimeout(() => (flag === "help" ? openHelp() : open()), 1500);

  return { fuzzyScore, rank, SHORTCUTS, open, close, openHelp };
});
