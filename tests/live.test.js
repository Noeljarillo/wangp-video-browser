"use strict";
/* P1.5: live merge of SSE changes. Run with `node --test tests/`. */
const test = require("node:test");
const assert = require("node:assert");
const { merge, toastText } = require("../app/web/live.js");

test("merge inserts new clips newest first and dedupes", () => {
  const base = [{ id: "a", mtime: 3 }, { id: "b", mtime: 1 }];
  const { videos, fresh } = merge(base, [{ id: "c", mtime: 2 }, { id: "a", mtime: 3 }], []);
  assert.deepStrictEqual(videos.map((v) => v.id), ["a", "c", "b"]);
  assert.deepStrictEqual(fresh.map((v) => v.id), ["c"]);
});

test("merge drops removed ids", () => {
  const { videos } = merge([{ id: "a", mtime: 1 }, { id: "b", mtime: 2 }], [], ["b"]);
  assert.deepStrictEqual(videos.map((v) => v.id), ["a"]);
});

test("toast names the render", () => {
  assert.strictEqual(toastText([{ id: "x", name: "x.mp4", meta: { prompt: "a cat\nmore" } }]), "New render: a cat");
  assert.strictEqual(toastText([{ id: "x", name: "x.mp4" }, { id: "y" }]), "2 new renders: x.mp4");
  assert.strictEqual(toastText([]), "");
});
