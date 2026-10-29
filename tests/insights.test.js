/* P5.2 Insights: bucket maths and the takeaway wording, against synthetic libraries.

   These are the two places a bug would show up as a confident-but-wrong claim, so they
   are tested directly rather than through the DOM: a bucket must average only the clips
   it contains, and a takeaway must stay honest when there is nothing to compare. */
"use strict";

const test = require("node:test");
const assert = require("node:assert");
const INS = require("../app/web/insights.js");

function clip(id, rating, meta, status) {
  return { id: id, meta: meta || {}, lib: rating ? { rating: rating, status: status || null } : {} };
}

test("numeric buckets group by exact value and average only rated clips", function () {
  const rows = INS.rowsFor({ key: "num_inference_steps", label: "Steps", kind: "num" },
    [clip("a", 5, { num_inference_steps: 8 }), clip("b", 3, { num_inference_steps: 8 }),
     clip("c", 0, { num_inference_steps: 8 }), clip("d", 2, { num_inference_steps: 20 })], {});
  const groups = INS.buckets(rows);
  assert.deepStrictEqual(groups.map(function (g) { return g.x; }), [8, 20]);
  assert.strictEqual(groups[0].n, 3);
  assert.strictEqual(groups[0].rated, 2);
  assert.strictEqual(groups[0].meanRated, 4);          // (5+3)/2, the unrated clip stays out
  assert.strictEqual(groups[1].meanRated, 2);
});

test("a wide numeric range is binned so the axis stays readable", function () {
  const clips = [];
  for (let i = 0; i < 20; i += 1) clips.push(clip("c" + i, (i % 5) + 1, { guidance_scale: 1 + i * 0.1 }));
  const rows = INS.rowsFor({ key: "guidance_scale", label: "Guidance", kind: "num" },
    clips.map(function (c) { return c; }), {});
  const groups = INS.buckets(rows);
  assert.ok(groups.length <= 8, "at most 8 columns: got " + groups.length);
  assert.match(groups[0].label, /^[0-9.]+–[0-9.]+$/);       // a range, not one value
  assert.ok(groups.reduce(function (n, g) { return n + g.n; }, 0) >= 20 - 1);  // nothing lost
});

test("clips without the setting are dropped, not bucketed as zero", function () {
  const rows = INS.rowsFor({ key: "guidance_scale", label: "Guidance", kind: "num" },
    [clip("a", 4, { guidance_scale: 5 }), clip("b", 4, {}), clip("c", 4, { guidance_scale: null })], {});
  assert.strictEqual(rows.length, 1);
});

test("lora weight reads the largest absolute multiplier", function () {
  assert.strictEqual(INS.metaValue({ meta: { loras_multipliers: ["1", "0.6"] } }, "lora_weight"), 1);
  assert.strictEqual(INS.metaValue({ meta: { loras_multipliers: "0.8;1.3" } }, "lora_weight"), 1.3);
  assert.strictEqual(INS.metaValue({ meta: {} }, "lora_weight"), null);
});

test("shift falls back across the names WanGP has used", function () {
  assert.strictEqual(INS.metaValue({ meta: { sample_shift: 5 } }, "shift"), 5);
  assert.strictEqual(INS.metaValue({ meta: { flow_shift: "3" } }, "shift"), 3);
});

test("a conclusion needs rated clips at two values", function () {
  const one = [{ x: 8, n: 4, rated: 4, meanRated: 4, keeps: 0, rejects: 0 }];
  assert.match(INS.takeaway({ label: "Steps", kind: "num" }, one, 4), /Only one steps value/);

  const none = [{ x: 8, n: 4, rated: 0, meanRated: 0, keeps: 0, rejects: 0 },
                { x: 20, n: 4, rated: 0, meanRated: 0, keeps: 0, rejects: 0 }];
  assert.strictEqual(INS.takeaway({ label: "Steps", kind: "num" }, none, 0), null);

  const flat = [{ x: 8, n: 3, rated: 3, meanRated: 3.1, keeps: 0, rejects: 0 },
                { x: 20, n: 3, rated: 3, meanRated: 3.2, keeps: 0, rejects: 0 }];
  assert.match(INS.takeaway({ label: "Steps", kind: "num" }, flat, 6), /no clear difference/);

  const clear = [{ x: 8, n: 3, rated: 3, meanRated: 4.4, keeps: 2, rejects: 0 },
                 { x: 20, n: 3, rated: 3, meanRated: 2.2, keeps: 0, rejects: 1 }];
  const said = INS.takeaway({ label: "Steps", kind: "num" }, clear, 6);
  assert.match(said, /scores best at 8/);
  assert.match(said, /4\.4 stars over 3 rated clips/);   // the number matches the bucket
});

test("categorical buckets sort by average rating and carry keep/reject counts", function () {
  const rows = INS.rowsFor({ key: "model_type", label: "Model", kind: "cat" },
    [clip("a", 5, { model_type: "wan2.2" }), clip("b", 4, { model_type: "wan2.2" }, "keep"),
     clip("c", 1, { model_type: "ltx" }, "reject")], {});
  const groups = INS.catBuckets(rows);
  assert.deepStrictEqual(groups.map(function (g) { return g.x; }), ["wan2.2", "ltx"]);
  assert.strictEqual(groups[0].meanRated, 4.5);
  assert.strictEqual(groups[0].keeps, 1);
  assert.strictEqual(groups[1].rejects, 1);
});

/* A 30-line DOM shim: enough for render() to build its cards, so the view itself
   (not just the maths) is covered by a test that runs without a browser. */
function shimDocument() {
  function node(tag) {
    return {
      tagName: tag, children: [], attributes: {}, className: "", textContent: "", innerHTML: "",
      append: function () { this.children.push.apply(this.children, arguments); },
      replaceChildren: function () { this.children = [].slice.call(arguments); },
      setAttribute: function (k, v) { this.attributes[k] = v; },
    };
  }
  return { createElement: node, createElementNS: function (_ns, tag) { return node(tag); },
    getElementById: function () { return node("div"); } };
}

function walk(node, out) {
  out = out || [];
  (node.children || []).forEach(function (child) { out.push(child); walk(child, out); });
  return out;
}

test("render() builds one card per available setting and states its takeaway", function () {
  var realDoc = global.document;
  global.document = shimDocument();
  try {
    var videos = [
      clip("a", 5, { num_inference_steps: 8, guidance_scale: 5, model_type: "wan2.2" }),
      clip("b", 4, { num_inference_steps: 8, guidance_scale: 5, model_type: "wan2.2" }),
      clip("c", 1, { num_inference_steps: 20, guidance_scale: 5, model_type: "ltx" }),
      clip("d", 2, { num_inference_steps: 20, guidance_scale: 5, model_type: "ltx" }),
    ];
    var host = shimDocument().createElement("div");
    INS.view(host, videos, { defects: {}, consistency: {} });
    var nodes = walk(host);
    var cards = nodes.filter(function (n) { return n.className === "ins-card"; });
    assert.strictEqual(cards.length, 2);            // steps and model; guidance has one value
    var takes = nodes.filter(function (n) { return /^ins-take/.test(n.className); });
    assert.strictEqual(takes.length, 2);
    assert.match(takes.map(function (t) { return t.textContent; }).join(" "), /scores best at 8/);
    assert.ok(nodes.some(function (n) { return n.tagName === "svg"; }), "charts are inline svg");
  } finally {
    global.document = realDoc;
  }
});

test("render() with no rated clips says so instead of drawing a trend", function () {
  var realDoc = global.document;
  global.document = shimDocument();
  try {
    var videos = [clip("a", 0, { num_inference_steps: 8 }), clip("b", 0, { num_inference_steps: 8 }),
      clip("c", 0, { num_inference_steps: 20 })];
    var host = shimDocument().createElement("div");
    INS.view(host, videos, { defects: {}, consistency: {} });
    var takes = walk(host).filter(function (n) { return /^ins-take/.test(n.className); });
    assert.match(takes[0].textContent, /Not enough rated clips/);
    assert.match(walk(host).filter(function (n) { return n.tagName === "p"; })[0].textContent,
      /0 of 3 clips are rated/);
  } finally {
    global.document = realDoc;
  }
});

test("defect and consistency sources are read by clip id", function () {
  const rows = INS.rowsFor({ key: "aesthetic", label: "Aesthetic", kind: "num", defects: true },
    [clip("a", 5, {}), clip("b", 2, {})], { defects: { a: { aesthetic: 5.5 }, b: { aesthetic: 3.1 } } });
  assert.deepStrictEqual(rows.map(function (r) { return r.x; }), [5.5, 3.1]);
  const none = INS.rowsFor({ key: "aesthetic", label: "Aesthetic", kind: "num", defects: true },
    [clip("a", 5, {})], {});
  assert.strictEqual(none.length, 0);
});
