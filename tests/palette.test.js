/* node --test tests/palette.test.js  (P6.2: command palette) */
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { fuzzyScore, rank, SHORTCUTS } = require(path.join(__dirname, "..", "app", "web", "palette.js"));

test("fuzzyScore: substring beats subsequence, no match is -1", () => {
  assert.equal(fuzzyScore("xyz", "compare"), -1);
  assert.ok(fuzzyScore("comp", "Go to Compare") > fuzzyScore("cmpr", "Go to Compare"));
  assert.ok(fuzzyScore("cmpr", "Go to Compare") > 0);
  assert.equal(fuzzyScore("", "anything"), 0);
});

test("fuzzyScore: word start ranks above mid-word", () => {
  assert.ok(fuzzyScore("grid", "Library as grid") > fuzzyScore("rid", "Library as grid"));
});

test("rank orders best first, keeps order on empty query, uses keywords", () => {
  const items = [
    { label: "Go to Timeline" },
    { label: "Go to Compare" },
    { label: "2025-01-01-10h00m00s_seed42_x.mp4", keywords: "a cat walks seed 42" },
  ];
  assert.deepEqual(rank(items, "").map((i) => i.label), items.map((i) => i.label));
  assert.equal(rank(items, "compare")[0].label, "Go to Compare");
  assert.equal(rank(items, "cat walks")[0].label, items[2].label);
  assert.equal(rank(items, "seed42")[0].label, items[2].label);
  assert.equal(rank(items, "qqq").length, 0);
  assert.equal(rank(items, "go", 1).length, 1);
});

test("SHORTCUTS covers palette, triage and compare keys", () => {
  const keys = SHORTCUTS.flatMap(([, rows]) => rows.map(([k]) => k));
  for (const k of ["Ctrl/Cmd+K", "?", "K", "X", "G", "B", "1 - 5"]) assert.ok(keys.includes(k), k);
});
