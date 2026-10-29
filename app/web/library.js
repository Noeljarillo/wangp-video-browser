/* WanGP Video Browser - library triage (P2.3).
   Ratings (1-5), keep (K) / reject (X), free tags and named collections, stored
   server-side in app/.data/library.json keyed by content id, never in the
   videos. Loaded after app.js and uses its globals (state, el, $, FACETS ...);
   app.js calls back through window.WVB_LIB at three small hooks. */
(function () {
  "use strict";

  const NONE = "\u0000none";
  const LS_REJECTS = "wvb-show-rejects";
  let showRejects = false;
  try { showRejects = localStorage.getItem(LS_REJECTS) === "1"; } catch (e) { /* private mode */ }

  const lib = (video) => (video && video.lib) || {};
  const STAR_PATH = "M8 1.9l1.8 3.9 4.2.5-3.1 2.9.8 4.2L8 11.3l-3.7 2.1.8-4.2L2 6.3l4.2-.5z";
  const star = (filled) => {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("class", `ic lib-star${filled ? " on" : ""}`);
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", STAR_PATH);
    path.setAttribute("stroke-linejoin", "round");
    svg.append(path);
    return svg;
  };

  /* ---- filters: auto-detected like the others, so they appear only once a
     clip in the library has a rating, status, tag or collection. */
  const RATING_SHOW = (x) => (x === NONE ? "Unrated" : `${x} star${x === "1" ? "" : "s"}`);
  FACETS.push(
    { key: "rating", label: "Rating", all: "Any rating", cls: "time",
      values: (v) => [lib(v).rating ? String(lib(v).rating) : NONE], show: RATING_SHOW },
    { key: "status", label: "Status", all: "Any status", cls: "post",
      values: (v) => [lib(v).status || NONE],
      show: (x) => ({ keep: "Kept", reject: "Rejected", [NONE]: "Undecided" })[x] || x },
    { key: "tag", label: "Tag", all: "Any tag", cls: "seed",
      values: (v) => ((lib(v).tags || []).length ? lib(v).tags : [NONE]), show: (x) => (x === NONE ? "No tag" : x) },
    { key: "collection", label: "Collection", all: "Any collection", cls: "shape",
      values: (v) => ((lib(v).collections || []).length ? lib(v).collections : [NONE]),
      show: (x) => (x === NONE ? "In no collection" : x) },
  );

  const hidden = (video) => !showRejects && lib(video).status === "reject" && state.facets.status !== "reject";

  /* ---- persistence */
  async function update(ids, patch) {
    const response = await fetch("/api/library/update", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids, patch }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || response.statusText);
    for (const [id, item] of Object.entries(data.items || {})) {
      const video = state.videos.find((v) => v.id === id);
      if (video) video.lib = item;
    }
    refresh();
    return data;
  }
  const save = (ids, patch, message) => update(ids, patch).then(() => message && flash(message))
    .catch((error) => flash(`Could not save: ${error.message}`));

  /* Re-render the sidebar and the triage bar only - re-rendering the preview
     would restart its player on every keypress. */
  function refresh() {
    const focusedId = document.activeElement && document.activeElement.dataset
      ? document.activeElement.dataset.id : null;
    renderFacets();
    renderList();
    renderTools();
    const bar = $("#libBar");
    const active = getVideo(state.activeId);
    if (bar && active) bar.replaceWith(previewBar(active));
    if (focusedId) focusCard(focusedId);
  }

  const allCollections = () => [...new Set(state.videos.flatMap((v) => lib(v).collections || []))].sort();
  const allTags = () => [...new Set(state.videos.flatMap((v) => lib(v).tags || []))].sort();
  const splitList = (text) => String(text || "").split(",").map((t) => t.trim()).filter(Boolean);

  /* ---- card decoration */
  function decorateCard(card, video) {
    const item = lib(video);
    card.dataset.id = video.id;
    if (item.status) card.classList.add(`lib-${item.status}`);
    const parts = [];
    if (item.rating) {
      parts.push(el("span", { className: "lib-stars", title: `${item.rating} of 5` },
        [1, 2, 3, 4, 5].map((n) => star(n <= item.rating))));
    }
    if (item.status) parts.push(el("span", { className: `lib-status ${item.status}` }, item.status === "keep" ? "Keep" : "Reject"));
    for (const tag of item.tags || []) parts.push(el("span", { className: "lib-tag" }, `#${tag}`));
    for (const name of item.collections || []) parts.push(el("span", { className: "lib-coll" }, name));
    if (!parts.length) return;
    const body = card.querySelector(".card-body");
    const foot = body && body.querySelector(".card-foot");
    const line = el("div", { className: "lib-line" }, parts);
    if (foot) foot.before(line); else if (body) body.append(line);
    const label = card.getAttribute("aria-label") || "";
    const said = [item.rating ? `${item.rating} stars` : "", item.status === "keep" ? "kept" : item.status === "reject" ? "rejected" : ""]
      .filter(Boolean).join(", ");
    if (said) card.setAttribute("aria-label", `${label} — ${said}`);
  }

  /* ---- preview triage bar */
  function chipList(values, cls, remove) {
    return values.map((value) => el("button", {
      className: `lib-chip ${cls}`, title: `Remove ${value}`, ariaLabel: `Remove ${value}`,
      onclick: () => remove(value),
    }, [value, icon("close")]));
  }

  function listEditor(video, key, placeholder, suggestions) {
    const item = lib(video);
    const current = item[key] || [];
    const listId = `lib-${key}-options`;
    const input = el("input", {
      type: "text", id: key === "tags" ? "libTagInput" : "libCollInput", placeholder,
      ariaLabel: placeholder, autocomplete: "off",
    });
    input.setAttribute("list", listId);
    const add = () => {
      const values = splitList(input.value);
      if (!values.length) return;
      save([video.id], { [key]: [...current, ...values] });
    };
    input.onkeydown = (event) => {
      if (event.key === "Enter") { event.preventDefault(); add(); }
      else if (event.key === "Escape") { input.value = ""; input.blur(); }
    };
    return el("div", { className: `lib-editor ${key}` }, [
      ...chipList(current, key === "tags" ? "lib-tag" : "lib-coll",
        (value) => save([video.id], { [key]: current.filter((x) => x !== value) })),
      input,
      el("datalist", { id: listId }, suggestions().filter((s) => !current.includes(s)).map((s) => el("option", { value: s }))),
    ]);
  }

  function previewBar(video) {
    const item = lib(video);
    const stars = el("div", { className: "lib-rate", role: "group", ariaLabel: "Rating" },
      [1, 2, 3, 4, 5].map((n) => el("button", {
        className: "ghost ic-btn", title: `${n} star${n > 1 ? "s" : ""} (key ${n})`,
        ariaLabel: `Rate ${n} of 5`, ariaPressed: String(item.rating === n),
        onclick: () => setRating(video.id, n),
      }, star(n <= (item.rating || 0)))));
    const statusButton = (status, label, key) => el("button", {
      className: `ghost lib-${status}-btn${item.status === status ? " on" : ""}`,
      title: `${label} (key ${key})`, ariaPressed: String(item.status === status),
      onclick: () => setStatus(video.id, status, false),
    }, label);
    return el("div", { className: "lib-bar", id: "libBar" }, [
      stars,
      el("div", { className: "lib-decide", role: "group", ariaLabel: "Keep or reject" },
        [statusButton("keep", "Keep", "K"), statusButton("reject", "Reject", "X")]),
      listEditor(video, "tags", "Add tag (T)", allTags),
      listEditor(video, "collections", "Add to collection (C)", allCollections),
    ]);
  }

  /* ---- sidebar tools: show rejects + move rejects to trash */
  function renderTools() {
    let box = $("#libTools");
    if (!box) {
      box = el("div", { id: "libTools", className: "lib-tools" });
      $("#facets").after(box);
    }
    const rejects = state.videos.filter((v) => lib(v).status === "reject" && !v.external);
    const toggle = el("input", { type: "checkbox", id: "libShowRejects", checked: showRejects });
    toggle.onchange = () => {
      showRejects = toggle.checked;
      try { localStorage.setItem(LS_REJECTS, showRejects ? "1" : "0"); } catch (e) { /* ignore */ }
      renderList();
    };
    box.replaceChildren(
      el("label", { className: "lib-check", htmlFor: "libShowRejects" }, [toggle, ` Show rejects (${rejects.length})`]),
      rejects.length ? el("button", { className: "link lib-trash", onclick: () => trashRejects(rejects) },
        `Move ${rejects.length} reject${rejects.length > 1 ? "s" : ""} to trash`) : null,
    );
    box.hidden = !state.videos.length;
  }

  async function trashRejects(rejects) {
    const names = rejects.slice(0, 12).map((v) => `  ${v.name}`).join("\n");
    const more = rejects.length > 12 ? `\n  …and ${rejects.length - 12} more` : "";
    if (!confirm(`Move ${rejects.length} rejected clip${rejects.length > 1 ? "s" : ""} to the system trash?\n\n${names}${more}\n\nThey can be restored from the trash.`)) return;
    try {
      const response = await fetch("/api/library/trash", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: rejects.map((v) => v.id) }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || response.statusText);
      applyIndex(data);
      renderTools();
      flash(`Moved ${data.moved.length} to trash${data.errors.length ? `, ${data.errors.length} failed: ${data.errors[0].error}` : ""}`);
    } catch (error) {
      flash(`Could not move to trash: ${error.message}`);
    }
  }

  /* ---- actions */
  function setRating(id, n) {
    const current = lib(getVideo(id)).rating || 0;
    const next = current === n ? 0 : n;
    save([id], { rating: next }, next ? `Rated ${next} of 5` : "Rating cleared");
  }

  function setStatus(id, status, advance) {
    const current = lib(getVideo(id)).status;
    const next = current === status ? null : status;
    const after = advance ? neighbour(id, 1) : null;
    save([id], { status: next }, next ? (next === "keep" ? "Kept" : "Rejected") : "Status cleared")
      .then(() => { if (after) select(after); });
  }

  function neighbour(id, step) {
    const list = visibleVideos();
    const index = list.findIndex((v) => v.id === id);
    const next = list[index + step];
    return next ? next.id : null;
  }

  function focusCard(id) {
    const card = document.querySelector(`#list .card[data-id="${CSS.escape(id)}"]`);
    if (card) { card.focus({ preventScroll: true }); card.scrollIntoView({ block: "nearest" }); }
  }

  function select(id) {
    if (!id) return;
    state.activeId = id;
    renderAll();
    focusCard(id);
  }

  const targetId = () => {
    const node = document.activeElement;
    return (node && node.classList && node.classList.contains("card") && node.dataset.id) || state.activeId;
  };

  /* Keyboard triage: 1-5 rate (again to clear), 0 clear, K keep, X reject
     (both advance to the next clip), T tag, C collection, Up/Down or J
     move through the list. Compare view keeps its own keys. */
  document.addEventListener("keydown", (event) => {
    if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)) return;
    if (state.view === "compare") return;
    const id = targetId();
    const video = id && getVideo(id);
    if (!video || video.external) return;
    const key = event.key.toLowerCase();
    if (/^[0-5]$/.test(key)) { event.preventDefault(); setRating(id, Number(key)); }
    else if (key === "k") { event.preventDefault(); setStatus(id, "keep", true); }
    else if (key === "x") { event.preventDefault(); setStatus(id, "reject", true); }
    else if (key === "t" || key === "c") {
      event.preventDefault();
      if (id !== state.activeId) { state.activeId = id; renderAll(); }
      const input = $(key === "t" ? "#libTagInput" : "#libCollInput");
      if (input && input.offsetParent) input.focus();
      else {
        const text = prompt(key === "t" ? "Add tags (comma separated)" : "Add to collection");
        const field = key === "t" ? "tags" : "collections";
        if (text) save([id], { [field]: [...(lib(video)[field] || []), ...splitList(text)] });
      }
    } else if ((event.key === "ArrowDown" || event.key === "ArrowUp" || key === "j") &&
               (document.activeElement === document.body || document.activeElement.classList.contains("card"))) {
      const next = neighbour(id, event.key === "ArrowUp" ? -1 : 1);
      if (next) { event.preventDefault(); select(next); }
    }
  });

  window.WVB_LIB = { hidden, decorateCard, previewBar, refresh, update, renderTools };

  // Every list render (load, rescan, filter) also refreshes the reject tools.
  const baseRenderList = renderList;
  renderList = function () { baseRenderList(); renderTools(); };
})();
