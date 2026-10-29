"use strict";
/* P2.1: virtual scroller maths. Run with `node --test tests/`. */
const test = require("node:test");
const assert = require("node:assert");
const { layoutRows, offsetsOf, rowAt, windowOf, mockVideos } = require("../app/web/grid.js");

const entries = (n) => Array.from({ length: n }, (_, i) => ({ key: `e${i}`, ids: [`e${i}`] }));

test("rows pack `cols` entries, span entries take their own row", () => {
  const list = entries(7);
  list.splice(3, 0, { key: "big", ids: ["a", "b"], span: true });
  const rows = layoutRows(list, 3);
  assert.deepStrictEqual(rows.map((r) => r.entries.length), [3, 1, 3, 1]);
  assert.strictEqual(rows[1].span, true);
  assert.strictEqual(layoutRows(entries(5), 1).length, 5);
});

test("offsets and rowAt agree", () => {
  const rows = layoutRows(entries(10), 1);
  const off = offsetsOf(rows, (_, i) => (i % 2 ? 50 : 100));
  assert.strictEqual(off[10], 750);
  assert.strictEqual(rowAt(off, 0), 0);
  assert.strictEqual(rowAt(off, 99), 0);
  assert.strictEqual(rowAt(off, 100), 1);
  assert.strictEqual(rowAt(off, 10000), 9);
});

test("5000 entries render only a window of rows", () => {
  const rows = layoutRows(entries(5000), 4);
  assert.strictEqual(rows.length, 1250);
  const off = offsetsOf(rows, () => 160);
  const [start, end] = windowOf(off, 80000, 800, 600);
  assert.ok(end - start <= 15, `window ${start}-${end}`);
  assert.ok(off[start] <= 80000 - 600 && off[end] >= 80000 + 800 + 600);
});

test("mock library has unique ids and descending times", () => {
  const v = mockVideos(5000, [{ name: "a.mp4", meta: { prompt: "p" } }], 1.7e9);
  assert.strictEqual(new Set(v.map((x) => x.id)).size, 5000);
  assert.ok(v.every((x, i) => !i || x.mtime <= v[i - 1].mtime));
  assert.strictEqual(v[0].meta.prompt, "p");
});
