"use strict";
/* P3.0: analysis status chip labels. Run with `node --test tests/`. */
const test = require("node:test");
const assert = require("node:assert");
const { analysisLabel } = require("../app/web/analysis.js");

test("absent add-on shows the calm install state", () => {
  assert.strictEqual(analysisLabel({ installed: false, state: "absent" }).text, "Install analysis");
  assert.strictEqual(analysisLabel(null).tone, "absent");
});

test("queue progress, pause and done states", () => {
  const base = { installed: true, total: 40, done: 12, queued: 28, errors: 0 };
  assert.strictEqual(analysisLabel(Object.assign({ state: "running" }, base)).text, "Analysing 12/40");
  assert.strictEqual(analysisLabel(Object.assign({}, base, { state: "paused", reason: "wangp" })).text, "Analysis paused for WanGP");
  assert.strictEqual(analysisLabel(Object.assign({}, base, { state: "paused", reason: "vram" })).tone, "paused");
  assert.strictEqual(analysisLabel({ installed: true, state: "idle", total: 40, done: 40, queued: 0 }).text, "Analysis up to date");
});
