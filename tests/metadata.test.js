"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { metaSourceLabel, metaRawWorkflow } = require("../app/web/metadata.js");

test("source label", () => {
  assert.strictEqual(metaSourceLabel({ _source: "comfyui" }), "ComfyUI");
  assert.strictEqual(metaSourceLabel({ _source: "wangp" }), "WanGP");
  assert.strictEqual(metaSourceLabel({ _source: "unknown" }), null);
  assert.strictEqual(metaSourceLabel({}), null);
});

test("raw workflow prefers the UI workflow", () => {
  const workflow = { nodes: [] }, prompt = { 1: { class_type: "KSampler" } };
  assert.deepStrictEqual(JSON.parse(metaRawWorkflow({ _comfy: { workflow, prompt } })), workflow);
  assert.deepStrictEqual(JSON.parse(metaRawWorkflow({ _comfy: { workflow: null, prompt } })), prompt);
  assert.strictEqual(metaRawWorkflow({ seed: 1 }), null);
});
