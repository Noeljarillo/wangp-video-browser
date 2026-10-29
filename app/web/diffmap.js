/* Compare: difference heatmap (P5.3).
   Exactly two clips. Both play (synced by the shared compare transport) in
   hidden <video>s; every displayed frame is drawn into a small offscreen
   canvas, diffed per pixel and painted through a perceptual colour scale.
   Entirely client-side - nothing is computed or stored on the server. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.WVB_DIFFMAP = api;
}(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  const MAX_W = 640;            // working resolution; plenty for spotting change
  const GAINS = [1, 2, 4, 8];
  const CHANGED = 26;           // ~10% of full scale counts as "changed"
  // Magma-like stops: dark = identical, bright = very different.
  const STOPS = [[0, 0, 4], [59, 15, 112], [140, 41, 129], [222, 73, 104], [254, 159, 109], [252, 253, 191]];

  /* Pure helpers (unit tested). */
  function colormap(t) {
    const x = Math.max(0, Math.min(1, t)) * (STOPS.length - 1);
    const i = Math.min(STOPS.length - 2, Math.floor(x));
    const f = x - i;
    return STOPS[i].map((c, k) => Math.round(c + (STOPS[i + 1][k] - c) * f));
  }
  function buildLut() {
    const lut = new Uint8ClampedArray(256 * 3);
    for (let v = 0; v < 256; v++) lut.set(colormap(v / 255), v * 3);
    return lut;
  }
  /* a, b: RGBA byte arrays of equal length. Writes the heatmap into out (RGBA)
     and returns { mean, changed } as fractions of full scale / of pixels. */
  function diffPixels(a, b, out, gain = 1, lut = buildLut()) {
    let sum = 0, changed = 0;
    const n = a.length >> 2;
    for (let p = 0; p < a.length; p += 4) {
      const d = (Math.abs(a[p] - b[p]) + Math.abs(a[p + 1] - b[p + 1]) + Math.abs(a[p + 2] - b[p + 2])) / 3;
      sum += d;
      if (d >= CHANGED) changed++;
      const v = Math.min(255, Math.round(d * gain)) * 3;
      out[p] = lut[v]; out[p + 1] = lut[v + 1]; out[p + 2] = lut[v + 2]; out[p + 3] = 255;
    }
    return { mean: n ? sum / n / 255 : 0, changed: n ? changed / n : 0 };
  }
  const workSize = (w, h, max = MAX_W) => {
    if (!(w > 0 && h > 0)) return { w: max, h: Math.round(max * 9 / 16) };
    const s = Math.min(1, max / w);
    return { w: Math.max(1, Math.round(w * s)), h: Math.max(1, Math.round(h * s)) };
  };
  const pct = (f) => `${(f * 100).toFixed(f < 0.1 ? 1 : 0)}%`;

  /* ---- DOM (browser only; uses app.js globals el/icon/posterUrl/mediaUrl/fpsOf) ---- */
  let gain = 2;
  let raf = 0;

  function stop() { if (raf) cancelAnimationFrame(raf); raf = 0; }

  function build(videos, players, stamps) {
    stop();
    const [first, second] = videos;
    const mk = (video, n) => el("video", { className: "dm-src", preload: "auto", muted: true, playsInline: true,
      src: mediaUrl(video), ariaHidden: "true", tabIndex: -1, title: `Clip ${n}` });
    const va = mk(first, 1), vb = mk(second, 2);
    players.push(va, vb);   // players[0] stays the master clock

    const canvas = el("canvas", { className: "dm-canvas", role: "img",
      ariaLabel: "Per-pixel difference between clip 1 and clip 2; brighter means more different" });
    const stamp = el("span", { className: "stamp" }, [
      el("span", { className: "t" }, "0:00.00"), " ", el("span", { className: "frame" }, "f0"),
    ]);
    stamps.push({ node: stamp, fps: fpsOf(first), index: 0 });
    const label = (video, n) => `#${n}${(video.meta || {}).seed != null ? ` ${video.meta.seed}` : ""}`;
    const status = el("span", { className: "dm-status" }, "Loading frames…");
    const stack = el("div", { className: "stack diffmap" }, [va, vb, canvas,
      el("span", { className: "tag a" }, `${label(first, 1)} vs ${label(second, 2)}`), stamp]);

    const readout = el("span", { className: "dm-readout", ariaLive: "polite" }, "");
    const scaleMax = el("span", { className: "dm-max" }, "");
    const legendBar = el("canvas", { className: "dm-scale", width: 256, height: 1, ariaHidden: "true" });
    const lctx = legendBar.getContext("2d");
    const lut = buildLut();
    const img = lctx.createImageData(256, 1);
    for (let v = 0; v < 256; v++) img.data.set([lut[v * 3], lut[v * 3 + 1], lut[v * 3 + 2], 255], v * 4);
    lctx.putImageData(img, 0, 0);

    const select = el("select", {
      ariaLabel: "Difference gain",
      onchange: (event) => { gain = parseInt(event.target.value, 10); paintScale(); dirty = true; },
    }, GAINS.map((g) => el("option", { value: g, textContent: `Gain ${g}×`, selected: g === gain })));
    const paintScale = () => { scaleMax.textContent = `≥${pct(1 / gain)}`; };
    paintScale();

    const legend = el("div", { className: "dm-legend" }, [
      el("span", { className: "dm-title" }, "Difference"),
      el("span", { className: "dm-min" }, "0%"), legendBar, scaleMax,
      el("div", { className: "select compact dm-gain" }, [select, icon("down")]),
      readout, status,
    ]);

    // Offscreen work canvases; willReadFrequently keeps getImageData off the GPU path.
    const ca = document.createElement("canvas"), cb = document.createElement("canvas");
    const xa = ca.getContext("2d", { willReadFrequently: true });
    const xb = cb.getContext("2d", { willReadFrequently: true });
    const ctx = canvas.getContext("2d");
    let size = null, lastA = -1, lastB = -1, dirty = true, out = null, failed = false;

    const resize = () => {
      size = workSize(va.videoWidth, va.videoHeight);
      for (const c of [ca, cb, canvas]) { c.width = size.w; c.height = size.h; }
      out = ctx.createImageData(size.w, size.h);
      if (va.videoWidth && va.videoHeight) stack.style.aspectRatio = `${va.videoWidth} / ${va.videoHeight}`;
      dirty = true;
    };

    const frame = () => {
      raf = requestAnimationFrame(frame);
      if (failed || va.readyState < 2 || vb.readyState < 2) return;
      if (!size) resize();
      if (!dirty && va.currentTime === lastA && vb.currentTime === lastB) return;
      lastA = va.currentTime; lastB = vb.currentTime; dirty = false;
      try {
        // Different resolutions are stretched onto clip 1's frame.
        xa.drawImage(va, 0, 0, size.w, size.h);
        xb.drawImage(vb, 0, 0, size.w, size.h);
        const stats = diffPixels(xa.getImageData(0, 0, size.w, size.h).data,
          xb.getImageData(0, 0, size.w, size.h).data, out.data, gain, lut);
        ctx.putImageData(out, 0, 0);
        readout.textContent = `mean ${pct(stats.mean)} · changed ${pct(stats.changed)}`;
        status.textContent = "";
      } catch (error) {
        failed = true;
        status.textContent = "This clip can't be read into a canvas here.";
      }
    };
    va.addEventListener("loadedmetadata", () => { size = null; });
    va.addEventListener("seeked", () => { dirty = true; });
    vb.addEventListener("seeked", () => { dirty = true; });
    raf = requestAnimationFrame(frame);

    return el("div", { className: "dm-wrap" }, [stack, legend]);
  }

  return { colormap, buildLut, diffPixels, workSize, build, stop, GAINS };
}));
