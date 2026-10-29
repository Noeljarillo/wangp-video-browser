/* node --test tests/takes.test.js  (P2.4: takes and batches) */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { takeKey, groupTakes, takeNumbers, compareSet } = require(path.join(__dirname, "..", "app", "web", "takes.js"));

const PA = "subject_definitions: <Subject 1> is the chef.\nshot: close up";
const PB = "A cat walks across a sunny kitchen";
const PC = "Drone shot over a foggy forest";
const PD = "Neon city at night, rain";
let t = 1000;
const clip = (id, model, prompt, seed, lib = {}) =>
  ({ id, name: `${id}.mp4`, mtime: (t += 10), lib, meta: model == null ? {} : { model_type: model, prompt, seed } });

/* 18 synthetic clips shaped like the dev library (WanGP metadata). */
const FIXTURE = [
  clip("a1", "wan_t2v", PA, 1), clip("a2", "wan_t2v", PA, 2, { rating: 3 }), clip("a3", "wan_t2v", PA, 3),
  clip("a4", "wan_t2v", PA, 4, { rating: 5, status: "reject" }), clip("a5", "wan_t2v", PA, 5, { rating: 4, status: "keep" }),
  clip("a6", "wan_t2v", PA, 6),
  clip("x1", "minimax_h3", PA, 1), clip("x2", "minimax_h3", PA, 2),          // same prompt, other model
  clip("b1", "wan_t2v", PB, 7), clip("b2", "wan_t2v", `  ${PB.replace(/ /g, "  ")}\n`, 8),   // whitespace only differs
  clip("b3", "wan_t2v", PB, 7),                                              // same seed again, still a take
  clip("c1", "wan_t2v", PC, 9),
  clip("n1", null), clip("n2", null),                                        // no metadata: never grouped
  clip("d1", "ltx2", PD, 1), clip("d2", "ltx2", PD, 2, { status: "keep" }), clip("d3", "ltx2", PD, 3),
  clip("d4", "ltx2", PD, 4, { rating: 2 }),
];

test("fixture has 18 clips", () => assert.equal(FIXTURE.length, 18));

test("groups by prompt + model, ignoring seed and whitespace", () => {
  const groups = groupTakes(FIXTURE);
  assert.deepEqual(groups.map((g) => g.takes.map((v) => v.id)), [
    ["a1", "a2", "a3", "a4", "a5", "a6"], ["x1", "x2"], ["b1", "b2", "b3"], ["c1"], ["n1"], ["n2"],
    ["d1", "d2", "d3", "d4"],
  ]);
  assert.equal(groups.reduce((n, g) => n + g.count, 0), 18);
  assert.equal(takeKey(FIXTURE[12]), null);
});

test("cover is the best-rated take, rejects never win", () => {
  const covers = Object.fromEntries(groupTakes(FIXTURE).map((g) => [g.takes[0].id, g.cover.id]));
  assert.equal(covers.a1, "a5");   // 5-star reject loses to 4-star keep
  assert.equal(covers.x1, "x2");   // unrated: newest
  assert.equal(covers.d1, "d4");   // rating beats keep
  assert.equal(covers.n1, "n1");
});

test("take numbers are generation order (Take 3 of 6)", () => {
  const numbers = takeNumbers(FIXTURE);
  assert.deepEqual(numbers.get("a3"), { take: 3, of: 6, key: numbers.get("a1").key });
  assert.deepEqual([numbers.get("b2").take, numbers.get("b2").of], [2, 3]);
  assert.equal(numbers.get("n2").of, 1);
  // order of the input does not change numbering
  const shuffled = takeNumbers(FIXTURE.slice().reverse());
  assert.equal(shuffled.get("a3").take, 3);
});

test("group order follows the caller's sort", () => {
  const groups = groupTakes(FIXTURE.slice().reverse());
  assert.deepEqual(groups.map((g) => g.cover.id).slice(0, 3), ["d4", "n2", "n1"]);
});

test("compare all takes: best first, capped at 4, rejects last", () => {
  const [a] = groupTakes(FIXTURE);
  assert.deepEqual(compareSet(a), ["a5", "a2", "a6", "a3"]);
  assert.deepEqual(compareSet(a, 6).slice(-1), ["a4"]);
});
