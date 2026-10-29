// P4.2 tags.js: auto-tag groups become facets.
const test = require("node:test");
const assert = require("node:assert");
const TAGS = require("../app/web/tags.js");

const body = {
  groups: [{ id: "time", label: "Time of day", labels: ["day", "night"] }, { id: "motion", label: "Camera motion", labels: ["static", "pan"] }],
  tags: { a: { time: "night", motion: "pan" }, b: { time: "day" } },
};

test("install adds one facet per group, idempotently", () => {
  const facets = [{ key: "model" }];
  TAGS.install(facets, body);
  TAGS.install(facets, body);
  assert.deepStrictEqual(facets.map((f) => f.key), ["model", "auto_time", "auto_motion"]);
});

test("facet values come from the clip's tags", () => {
  const facets = TAGS.install([], body);
  const time = facets[0], motion = facets[1];
  assert.deepStrictEqual(time.values({ id: "a" }), ["night"]);
  assert.deepStrictEqual(motion.values({ id: "b" }), []);
  assert.deepStrictEqual(time.values({ id: "zzz" }), []);
  assert.strictEqual(time.show("night"), "Night");
  assert.strictEqual(time.all, "Any time of day");
});
