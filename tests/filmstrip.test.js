"use strict";
/* P2.2: filmstrip maths. Run with `node --test tests/`. */
const test = require("node:test");
const assert = require("node:assert");
const { frameTimes, frameAt, spritePos, clock } = require("../app/web/filmstrip.js");

test("frame times sit at the centre of eight slices", () => {
  assert.deepStrictEqual(frameTimes(8), [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5]);
  assert.deepStrictEqual(frameTimes(0), []);
});

test("pointer fraction maps to a frame, clamped", () => {
  assert.strictEqual(frameAt(0), 0);
  assert.strictEqual(frameAt(0.49), 3);
  assert.strictEqual(frameAt(1), 7);
  assert.strictEqual(frameAt(-1), 0);
});

test("sprite positions and clock", () => {
  assert.strictEqual(spritePos(0), "0% 0");
  assert.strictEqual(spritePos(7), "100% 0");
  assert.strictEqual(clock(65.25), "1:05.3");
});
