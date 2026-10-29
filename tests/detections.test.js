"use strict";
/* P3.2: detections overlay helpers. Run with `node --test tests/`. */
const test = require("node:test");
const assert = require("node:assert");
const { nearestFrame, videoRect, boxesFor } = require("../app/web/detections.js");

test("nearest sampled frame", () => {
  assert.strictEqual(nearestFrame([0, 1, 2, 3], 1.4), 1);
  assert.strictEqual(nearestFrame([0, 1, 2, 3], 9), 3);
  assert.strictEqual(nearestFrame([], 1), -1);
});

test("object-fit contain rect", () => {
  assert.deepStrictEqual(videoRect(1600, 900, 832, 480), { x: 20, y: 0, w: 1560, h: 900 });
  const r = videoRect(1600, 900, 480, 832);
  assert.strictEqual(r.h, 900);
  assert.ok(Math.abs(r.x - (1600 - 480 * 900 / 832) / 2) < 1e-9);
  assert.deepStrictEqual(videoRect(100, 50, 0, 0), { x: 0, y: 0, w: 100, h: 50 });
});

test("boxes of the current frame only", () => {
  const data = { times: [0, 1, 2], detections: [{ frame: 0 }, { frame: 1 }, { frame: 1 }] };
  assert.strictEqual(boxesFor(data, 1.2).length, 2);
  assert.strictEqual(boxesFor(data, 0).length, 1);
  assert.strictEqual(boxesFor({ detections: [] }, 0).length, 0);
});
