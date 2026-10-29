/* P3.2 detections overlay: face / person boxes on the current frame of the preview player.
   Data: GET /api/analysis/detections/<id> (boxes normalised 0..1 per sampled frame). */
(function (root) {
  "use strict";

  var STORE = "wvb.detections";

  /* Index of the sampled frame nearest to `t` seconds (times sorted ascending). */
  function nearestFrame(times, t) {
    if (!times || !times.length) return -1;
    var best = 0, gap = Infinity;
    for (var i = 0; i < times.length; i++) {
      var d = Math.abs(times[i] - t);
      if (d < gap) { gap = d; best = i; }
    }
    return best;
  }

  /* Displayed picture rect inside a box of boxW x boxH with object-fit: contain. */
  function videoRect(boxW, boxH, vidW, vidH) {
    if (!vidW || !vidH || !boxW || !boxH) return { x: 0, y: 0, w: boxW, h: boxH };
    var scale = Math.min(boxW / vidW, boxH / vidH);
    var w = vidW * scale, h = vidH * scale;
    return { x: (boxW - w) / 2, y: (boxH - h) / 2, w: w, h: h };
  }

  function boxesFor(data, t) {
    if (!data || !data.detections || !data.detections.length) return [];
    var frame = nearestFrame(data.times, t);
    if (frame < 0) frame = 0;
    return data.detections.filter(function (d) { return d.frame === frame; });
  }

  function enabled() {
    if (root.location && /[?&]det=1\b/.test(root.location.search)) return true;   // dev / screenshot flag
    try { return root.localStorage.getItem(STORE) === "1"; } catch (e) { return false; }
  }
  function remember(on) {
    try { root.localStorage.setItem(STORE, on ? "1" : "0"); } catch (e) { /* private mode */ }
  }

  function attach(player, video) {
    if (!player || !video || video.external) return;
    var media = player.querySelector("video");
    var layer = document.createElement("div");
    layer.className = "det-layer";
    layer.setAttribute("aria-hidden", "true");
    var button = document.createElement("button");
    button.type = "button";
    button.className = "det-toggle";
    button.textContent = "Detections";
    button.title = "Show detected faces and people on the current frame";
    var data = null, loading = false, on = enabled();

    function paint() {
      layer.textContent = "";
      button.setAttribute("aria-pressed", on ? "true" : "false");
      button.classList.toggle("on", on);
      if (!on || !data) return;
      if (data.state !== "done") {
        button.title = data.state === "absent" ? "Install the analysis add-on to detect faces and people"
          : "Detections are still being analysed";
        return;
      }
      var rect = videoRect(media.clientWidth, media.clientHeight, media.videoWidth, media.videoHeight);
      boxesFor(data, media.currentTime || 0).forEach(function (d) {
        var b = document.createElement("div");
        b.className = "det-box det-" + d.kind;
        b.style.left = (media.offsetLeft + rect.x + d.x * rect.w) + "px";
        b.style.top = (media.offsetTop + rect.y + d.y * rect.h) + "px";
        b.style.width = (d.w * rect.w) + "px";
        b.style.height = (d.h * rect.h) + "px";
        var tag = document.createElement("span");
        tag.textContent = d.kind + " " + Math.round(d.score * 100);
        b.appendChild(tag);
        layer.appendChild(b);
      });
    }

    function load() {
      if (data || loading) return paint();
      loading = true;
      fetch("/api/analysis/detections/" + encodeURIComponent(video.id))
        .then(function (r) { return r.json(); })
        .then(function (json) { data = json; })
        .catch(function () { data = { state: "error", detections: [] }; })
        .then(function () { loading = false; paint(); });
    }

    button.addEventListener("click", function (event) {
      event.stopPropagation();
      on = !on;
      remember(on);
      if (on) load(); else paint();
    });
    ["timeupdate", "seeked", "loadedmetadata"].forEach(function (name) {
      media.addEventListener(name, function () { if (on) paint(); });
    });
    if (root.ResizeObserver) new root.ResizeObserver(function () { if (on) paint(); }).observe(media);
    player.appendChild(layer);
    player.appendChild(button);
    if (on) load(); else paint();
  }

  var api = { nearestFrame: nearestFrame, videoRect: videoRect, boxesFor: boxesFor, attach: attach };
  root.WVB_DET = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
