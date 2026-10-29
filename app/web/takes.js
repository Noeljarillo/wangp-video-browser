/* WanGP Video Browser - takes and batches (P2.4).
   Pure grouping logic, no DOM: clips that share the same prompt and model
   (seed ignored) form one take group. Loaded in the browser as window.WVBTakes
   and in Node via require() for `node --test tests/takes.test.js`. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.WVBTakes = factory();
}(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const normPrompt = (text) => String(text == null ? "" : text).replace(/\s+/g, " ").trim();
  const modelOf = (meta) => String(meta.model_type || meta.type || "").trim();

  /* Group key, or null when a clip carries no prompt/model to group by. */
  function takeKey(video) {
    const meta = (video && video.meta) || {};
    const prompt = normPrompt(meta.prompt);
    const model = modelOf(meta);
    if (!prompt || !model) return null;
    return `${model}\u0001${prompt}`;
  }

  const libOf = (video) => (video && video.lib) || {};

  /* Best first: never a reject ahead of a non-reject, then rating, then kept,
     then newest. */
  function bestOrder(a, b) {
    const la = libOf(a), lb = libOf(b);
    return ((la.status === "reject") - (lb.status === "reject"))
      || ((lb.rating || 0) - (la.rating || 0))
      || ((lb.status === "keep") - (la.status === "keep"))
      || ((b.mtime || 0) - (a.mtime || 0))
      || String(a.id).localeCompare(String(b.id));
  }

  /* Take order is generation order: oldest is take 1. */
  const takeOrder = (a, b) => ((a.mtime || 0) - (b.mtime || 0)) || String(a.name || a.id).localeCompare(String(b.name || b.id));

  /* Groups in order of first appearance in `videos` (so the caller's sort and
     filters carry over). Each: { key, model, prompt, takes (take order),
     cover (best take), count }. Clips without a key are single groups. */
  function groupTakes(videos) {
    const groups = new Map();
    for (const video of videos || []) {
      const key = takeKey(video) || `\u0000solo:${video.id}`;
      let group = groups.get(key);
      if (!group) {
        const meta = video.meta || {};
        group = { key, model: modelOf(meta), prompt: normPrompt(meta.prompt), takes: [] };
        groups.set(key, group);
      }
      group.takes.push(video);
    }
    return [...groups.values()].map((group) => {
      group.takes.sort(takeOrder);
      group.cover = group.takes.slice().sort(bestOrder)[0];
      group.count = group.takes.length;
      return group;
    });
  }

  /* id -> { take, of, key } across a whole library ("Take 3 of 6"). */
  function takeNumbers(videos) {
    const out = new Map();
    for (const group of groupTakes(videos)) {
      group.takes.forEach((video, index) => out.set(video.id, { take: index + 1, of: group.count, key: group.key }));
    }
    return out;
  }

  /* The clips "Compare all takes" opens: best first, capped at `max`. */
  function compareSet(group, max = 4) {
    return group.takes.slice().sort(bestOrder).slice(0, max).map((v) => v.id);
  }

  return { takeKey, groupTakes, takeNumbers, compareSet, bestOrder };
}));
