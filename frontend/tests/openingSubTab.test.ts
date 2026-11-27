import test from "node:test";
import assert from "node:assert/strict";
import { openingSubTab } from "../src/lib/subTabs.ts";

test("Risk Monitoring opens on Monitoring & Alerts when the route names no sub-tab", () => {
  assert.equal(openingSubTab(undefined), "monitoring");
  assert.equal(openingSubTab(""), "monitoring");
});

test("a named, legacy or unknown sub-tab opens as before", () => {
  assert.equal(openingSubTab("profiles"), "profiles");
  assert.equal(openingSubTab("ask"), "ask");
  assert.equal(openingSubTab("holdings"), "holdings");
  assert.equal(openingSubTab("dashboards"), "monitoring");
  assert.equal(openingSubTab("pivot"), "monitoring");
  assert.equal(openingSubTab("nope"), "monitoring");
});
