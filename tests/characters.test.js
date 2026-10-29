"use strict";
/* P3.3: character helpers. Run with `node --test tests/*.test.js`. */
const test = require("node:test");
const assert = require("node:assert");
const { indexByVideo, passes } = require("../app/web/characters.js");

test("video -> characters map skips ignored ones", () => {
  const map = indexByVideo([
    { id: "a", name: "Mara", clips: ["v1", "v2"] },
    { id: "b", name: "", clips: ["v2"], ignored: true },
    { id: "c", name: "", clips: ["v2"] },
  ]);
  assert.deepStrictEqual(map.v1.map((c) => c.id), ["a"]);
  assert.deepStrictEqual(map.v2.map((c) => c.id), ["a", "c"]);
  assert.strictEqual(map.v3, undefined);
});

test("character filter", () => {
  assert.ok(passes(null, "v1"));
  assert.ok(passes({ clips: ["v1"] }, "v1"));
  assert.ok(!passes({ clips: ["v1"] }, "v2"));
});
