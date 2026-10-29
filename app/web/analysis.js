/* Analysis add-on status chip (P3.0). Polls GET /api/analysis/status. */
(function (root) {
  "use strict";

  function analysisLabel(s) {
    if (!s || !s.installed) {
      return { text: "Install analysis", tone: "absent",
        title: "Character and content analysis is an optional add-on. Install it from the Pinokio menu (Install analysis). The browser works fully without it." };
    }
    var progress = s.total ? s.done + "/" + s.total : "";
    if (s.state === "paused") {
      return s.reason === "vram"
        ? { text: "Analysis waiting for VRAM", tone: "paused", title: "Not enough free GPU memory under the VRAM ceiling. Resumes automatically." }
        : { text: "Analysis paused for WanGP", tone: "paused", title: "A WanGP generation is using the GPU. Analysis resumes when it finishes." + (progress ? " " + progress + " done." : "") };
    }
    if (s.state === "stopped") {
      return { text: "Analysis stopped", tone: "idle", title: "The analysis worker is not running." + (progress ? " " + progress + " done." : "") };
    }
    if (s.queued > 0 || s.state === "running") {
      return { text: "Analysing " + progress, tone: "busy", title: (s.job ? "Now: " + s.job + ". " : "") + (s.errors ? s.errors + " failed." : "") };
    }
    return { text: "Analysis up to date", tone: "idle", title: (s.total || 0) + " jobs done" + (s.errors ? ", " + s.errors + " failed" : "") + "." };
  }

  function mount() {
    var status = document.getElementById("status");
    if (!status || document.getElementById("analysisChip")) return;
    var chip = document.createElement("span");
    chip.id = "analysisChip";
    chip.className = "an-chip";
    chip.tabIndex = 0;
    chip.setAttribute("role", "status");
    chip.hidden = true;
    chip.innerHTML = '<span class="an-dot" aria-hidden="true"></span><span class="an-text"></span><span class="an-bar" aria-hidden="true"><i></i></span>';
    status.parentNode.insertBefore(chip, status);

    var timer = null;
    function render(s) {
      var label = analysisLabel(s);
      chip.hidden = false;
      chip.dataset.tone = label.tone;
      chip.title = label.title;
      chip.setAttribute("aria-label", label.text + ". " + label.title);
      chip.querySelector(".an-text").textContent = label.text;
      var pct = s && s.total ? Math.round((100 * s.done) / s.total) : 0;
      chip.querySelector(".an-bar i").style.width = (label.tone === "busy" ? pct : 0) + "%";
      return label;
    }
    function poll() {
      fetch("/api/analysis/status", { cache: "no-store" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (s) {
          var label = render(s);
          if (!s || !s.installed) return; // calm: nothing to poll for
          timer = setTimeout(poll, label.tone === "idle" ? 15000 : 3000);
        })
        .catch(function () { timer = setTimeout(poll, 15000); });
    }
    poll();
    root.WVBAnalysis = { refresh: function () { clearTimeout(timer); poll(); } };
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { analysisLabel: analysisLabel };
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
})(typeof window !== "undefined" ? window : globalThis);
