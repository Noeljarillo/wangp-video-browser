"use strict";

/* ==========================================================================
   Re-run in WanGP (P1.4): "Export settings" downloads the clip's settings as
   the JSON WanGP loads via "Load Settings From Media File / Json / Zip".
   "New seed" exports the same settings with a fresh random seed. app.js only
   calls WVB_EXPORT.actions(video) in the preview header.
   ========================================================================== */

const WVB_EXPORT = (() => {
  const exportable = (video) => {
    const meta = (video && video.meta) || {};
    return !video.external && (meta._source === "wangp" || /WanGP/.test(String(meta.type || "")));
  };

  const download = (video, newSeed) => {
    const a = el("a", { href: `/api/export/${encodeURIComponent(video.id)}${newSeed ? "?new_seed=1" : ""}`, download: "" });
    document.body.append(a);
    a.click();
    a.remove();
    flash(newSeed ? "Settings exported with a new seed" : "Settings exported — load the file in WanGP");
  };

  function actions(video) {
    if (!video || !exportable(video)) return null;
    return el("div", { className: "exp-actions", role: "group", ariaLabel: "Re-run in WanGP" }, [
      el("button", {
        className: "ghost", title: "Download a settings file WanGP can load (Load Settings From Media File / Json / Zip)",
        onclick: () => download(video, false),
      }, [icon("down"), el("span", { className: "exp-label" }, "Export settings")]),
      el("button", {
        className: "ghost exp-seed", title: "Export the same settings with a new random seed",
        onclick: () => download(video, true),
      }, "New seed"),
    ]);
  }

  return { actions, exportable, download };
})();
window.WVB_EXPORT = WVB_EXPORT;
