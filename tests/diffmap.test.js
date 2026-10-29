"use strict";
const test = require("node:test");
const assert = require("node:assert");
const dm = require("../app/web/diffmap.js");

test("colormap endpoints and clamping", () => {
  assert.deepStrictEqual(dm.colormap(0), [0, 0, 4]);
  assert.deepStrictEqual(dm.colormap(1), [252, 253, 191]);
  assert.deepStrictEqual(dm.colormap(-1), dm.colormap(0));
  assert.deepStrictEqual(dm.colormap(2), dm.colormap(1));
});

test("colormap brightness rises monotonically", () => {
  let prev = -1;
  for (let i = 0; i <= 20; i++) {
    const [r, g, b] = dm.colormap(i / 20);
    const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
    assert.ok(lum >= prev, `step ${i}`);
    prev = lum;
  }
});

test("identical frames give zero difference and the darkest colour", () => {
  const a = new Uint8ClampedArray([10, 20, 30, 255, 200, 100, 50, 255]);
  const out = new Uint8ClampedArray(8);
  const s = dm.diffPixels(a, a.slice(), out, 4);
  assert.strictEqual(s.mean, 0);
  assert.strictEqual(s.changed, 0);
  assert.deepStrictEqual([...out.slice(0, 4)], [0, 0, 4, 255]);
});

test("full black vs white is max difference; gain saturates", () => {
  const a = new Uint8ClampedArray([0, 0, 0, 255, 0, 0, 0, 255]);
  const b = new Uint8ClampedArray([255, 255, 255, 255, 12, 12, 12, 255]);
  const out = new Uint8ClampedArray(8);
  const s = dm.diffPixels(a, b, out, 1);
  assert.ok(Math.abs(s.mean - (255 + 12) / 2 / 255) < 1e-9);
  assert.strictEqual(s.changed, 0.5);
  assert.deepStrictEqual([...out.slice(0, 3)], [252, 253, 191]);
  const out8 = new Uint8ClampedArray(8);
  dm.diffPixels(a, b, out8, 8);
  // 12 * 8 = 96 -> brighter than at gain 1
  assert.ok(out8[4] + out8[5] + out8[6] > out[4] + out[5] + out[6]);
});

test("workSize caps width and keeps aspect", () => {
  assert.deepStrictEqual(dm.workSize(1280, 720), { w: 640, h: 360 });
  assert.deepStrictEqual(dm.workSize(320, 240), { w: 320, h: 240 });
  assert.deepStrictEqual(dm.workSize(0, 0), { w: 640, h: 360 });
});
