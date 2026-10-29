"use strict";
/* P2.5: session grouping. Run with `node --test tests/`. */
const test = require("node:test");
const assert = require("node:assert");
const { sessions, spanOf, fmtDur } = require("../app/web/timeline.js");

const clip = (id, end, gen) => ({ id, mtime: end + 0.5, meta: { creation_timestamp: end, generation_time: gen } });

test("render span ends at creation time and starts generation_time earlier", () => {
  assert.deepStrictEqual([spanOf(clip("a", 1000, 300)).start, spanOf(clip("a", 1000, 300)).end], [700, 1000]);
  assert.strictEqual(spanOf({ id: "b", mtime: 50, meta: {} }).start, 50);
});

test("a gap over 30 minutes between renders starts a new session", () => {
  const t = 1_000_000;
  const videos = [
    clip("a", t, 600), clip("b", t + 700, 600),            // back to back
    clip("c", t + 700 + 1800 + 600, 600),                  // idle exactly 30 min: same session
    clip("d", t + 700 + 1800 + 600 + 1801 + 600, 600),     // idle 30 min 1 s: new session
  ];
  const s = sessions(videos.reverse());
  assert.deepStrictEqual(s.map((x) => x.clips.map((c) => c.video.id)), [["a", "b", "c"], ["d"]]);
  assert.strictEqual(s[0].render, 1800);
});

test("the real 22-clip library splits into its two days", () => {
  // Shape of the dev library (2026-10-28 afternoon, 2026-10-29 evening).
  const day1 = Array.from({ length: 10 }, (_, i) => clip(`x${i}`, 1793206514 + i * 320, 300));
  const day2 = Array.from({ length: 12 }, (_, i) => clip(`y${i}`, 1793290851 + i * 1700, 1600));
  assert.strictEqual(sessions([...day2, ...day1]).length, 2);
});

test("durations format compactly", () => {
  assert.strictEqual(fmtDur(42), "42s");
  assert.strictEqual(fmtDur(588), "9m 48s");
  assert.strictEqual(fmtDur(7300), "2h 01m");
});
