/* Export comparisons (P6.1).
   An "Export" button in the compare dock opens a small dialog: side-by-side
   or wipe, MP4 / WebM / GIF, plus a contact-sheet PNG of the take group. The
   server renders with ffmpeg (one job at a time) into app/.cache/exports/ and
   this file polls the job and offers the download. Uses app.js globals. */
const WVB_EXPORT_CMP = (() => {
  let dlg = null;

  function takeGroupIds(ids) {
    if (!window.WVBTakes || !ids.length) return ids;
    const group = WVBTakes.groupTakes(state.videos).find((g) => g.takes.some((t) => t.id === ids[0]));
    return group && group.takes.length > 1 ? group.takes.slice(0, 16).map((t) => t.id) : ids;
  }

  async function poll(job, status) {
    while (job && (job.status === "queued" || job.status === "running")) {
      status.textContent = job.status === "queued" ? "Queued…" : "Rendering with ffmpeg…";
      await new Promise((r) => setTimeout(r, 1000));
      if (!dlg) return;
      const res = await fetch(`/api/compare/job/${encodeURIComponent(job.id)}`);
      job = await res.json();
    }
    if (!dlg) return;
    if (!job || job.status === "error") {
      status.replaceChildren(el("span", { className: "ecx-err" }, `Export failed: ${(job && job.error) || "unknown error"}`));
      return;
    }
    const mb = job.size ? ` (${(job.size / 1048576).toFixed(1)} MB)` : "";
    status.replaceChildren("Ready", mb, " ", el("a", { className: "ecx-dl", href: job.url, download: job.name }, `Download ${job.name}`));
  }

  async function run(body, status, buttons) {
    buttons.forEach((b) => { b.disabled = true; });
    status.textContent = "Starting…";
    try {
      const res = await fetch("/api/compare/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const job = await res.json();
      if (!res.ok) throw new Error(job.error || res.statusText);
      await poll(job, status);
    } catch (error) {
      status.replaceChildren(el("span", { className: "ecx-err" }, error.message));
    } finally {
      buttons.forEach((b) => { b.disabled = false; });
      syncWipe();
    }
  }

  let syncWipe = () => {};
  function open() {
    if (dlg) return;
    const ids = state.picks.filter((id) => !String(id).startsWith("local:"));
    const prev = document.activeElement;
    const close = () => { if (!dlg) return; dlg.remove(); dlg = null; if (prev && prev.isConnected) prev.focus(); };
    const status = el("p", { className: "ecx-status", role: "status", ariaLive: "polite" });
    const mode = el("select", { ariaLabel: "Layout", id: "ecxMode" }, [
      el("option", { value: "side", textContent: "Side by side" }),
      el("option", { value: "wipe", textContent: "Wipe" }),
    ]);
    mode.value = state.cmpMode === "wipe" && ids.length === 2 ? "wipe" : "side";
    const fmt = el("select", { ariaLabel: "Format", id: "ecxFmt" }, [["mp4", "MP4"], ["webm", "WebM"], ["gif", "GIF"]]
      .map(([v, t]) => el("option", { value: v, textContent: t })));
    const go = el("button", { className: "primary", type: "button" }, "Export video");
    const sheet = el("button", { type: "button" }, "Contact sheet (PNG)");
    const buttons = [go, sheet];
    syncWipe = () => { mode.options[1].disabled = ids.length !== 2; };
    syncWipe();
    go.onclick = () => run({ ids, mode: mode.value, format: fmt.value, wipe: state.wipe }, status, buttons);
    sheet.onclick = () => run({ ids: takeGroupIds(ids), kind: "sheet" }, status, buttons);
    if (!state.ffmpeg) {
      buttons.forEach((b) => { b.disabled = true; });
      status.textContent = "ffmpeg was not found, so exports are unavailable. Install ffmpeg and restart to enable them.";
    } else if (ids.length < 2) {
      go.disabled = true;
      status.textContent = "Pick at least two library clips to export a comparison.";
    }
    dlg = el("div", { className: "pal-scrim ecx-scrim", onmousedown: (e) => { if (e.target === dlg) close(); },
      onkeydown: (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); } } }, [
      el("div", { className: "ecx", role: "dialog", ariaModal: "true", ariaLabelledby: "ecxTitle" }, [
        el("div", { className: "ecx-head" }, [el("h2", { id: "ecxTitle" }, "Export comparison"),
          el("button", { className: "link", type: "button", onclick: close }, "Close")]),
        el("p", { className: "ecx-note" }, `${ids.length} clip${ids.length === 1 ? "" : "s"}, labelled with seed, steps and the settings that differ. Files are written to the app cache; your videos are not changed.`),
        el("div", { className: "ecx-row" }, [
          el("label", { htmlFor: "ecxMode" }, "Layout"), el("div", { className: "select compact" }, [mode, icon("down")]),
          el("label", { htmlFor: "ecxFmt" }, "Format"), el("div", { className: "select compact" }, [fmt, icon("down")]),
        ]),
        el("div", { className: "ecx-actions" }, buttons),
        status,
      ]),
    ]);
    document.body.append(dlg);
    (go.disabled ? dlg.querySelector("button.link") : go).focus();
  }

  const button = () => el("button", { className: "sm", type: "button", title: "Export this comparison as video or a contact sheet",
    onclick: open }, "Export");

  // Dev/screenshot flag (like grid.js ?layout=): ?compare=a,b&exportcmp=1
  if (new URLSearchParams(location.search).get("exportcmp")) setTimeout(open, 2000);

  return { open, button, takeGroupIds };
})();
window.WVB_EXPORT_CMP = WVB_EXPORT_CMP;
