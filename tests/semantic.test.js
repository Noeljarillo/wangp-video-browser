// P4.1 semantic.js: content-mode ranking and text fallback.
const test = require("node:test");
const assert = require("node:assert");

global.renderList = () => {};
const calls = [];
global.fetch = (url) => { calls.push(url); return Promise.resolve({ json: () => ({}) }); };
const SEM = require("../app/web/semantic.js");

const vids = [{ id: "a" }, { id: "b" }, { id: "c" }];

test("text mode keeps text results when the prompt matches", () => {
  assert.strictEqual(SEM.apply("night", vids, [vids[0]]), null);
});

test("empty query never goes to content", () => {
  SEM.setMode("content");
  assert.strictEqual(SEM.apply("", vids, vids), null);
  SEM.setMode("text");
});

test("fallback to content ranking when text matches nothing", () => {
  SEM._state.cache["night"] = { available: true, results: [
    { id: "c", time: 4, score: 0.03 }, { id: "a", time: 1, score: 0.01 }, { id: "b", time: 0, score: 0 }] };
  const out = SEM.apply("night", vids, []);
  assert.deepStrictEqual(out.map((v) => v.id), ["c", "a"]);
  assert.strictEqual(SEM._state.seekTo.c, 4);
});

test("content mode with unavailable add-on shows nothing", () => {
  SEM.setMode("content");
  SEM._state.cache["dog"] = { available: false, reason: "x", results: [] };
  assert.deepStrictEqual(SEM.apply("dog", vids, vids), []);
  SEM.setMode("text");
});

test("unknown query schedules a fetch and keeps text results in text mode", () => {
  assert.strictEqual(SEM.apply("zebra", vids, []), null);
});
