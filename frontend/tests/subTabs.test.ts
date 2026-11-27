import test from "node:test";
import assert from "node:assert/strict";
import { resolveSubTab, SUB_TABS } from "../src/lib/subTabs.ts";

const TABS = [{ id: "monitoring" }, { id: "profiles" }] as const;

test("resolveSubTab keeps a known id", () => {
  assert.equal(resolveSubTab("monitoring", TABS), "monitoring");
  assert.equal(resolveSubTab("profiles", TABS), "profiles");
});

test("resolveSubTab maps removed legacy ids to monitoring", () => {
  assert.equal(resolveSubTab("genbi", TABS), "monitoring");
  assert.equal(resolveSubTab("pivot", TABS), "monitoring");
  assert.equal(resolveSubTab("dashboards", TABS), "monitoring");
});

test("resolveSubTab falls back to monitoring for unknown or missing ids", () => {
  assert.equal(resolveSubTab("nope", TABS), "monitoring");
  assert.equal(resolveSubTab(undefined, TABS), "monitoring");
});

test("the standard and dashboards sub-tabs are gone and the default is monitoring", () => {
  assert.ok(!SUB_TABS.some((t) => t.id === "standard"));
  assert.ok(!SUB_TABS.some((t) => t.id === "dashboards"));
  assert.equal(SUB_TABS[0].id, "monitoring");
  assert.equal(resolveSubTab("standard", SUB_TABS), "monitoring");
  assert.equal(resolveSubTab(undefined, SUB_TABS), "monitoring");
});

test("the governance sub-tab is gone and its id falls back to the default", () => {
  assert.ok(!SUB_TABS.some((t) => t.id === "governance"));
  assert.equal(resolveSubTab("governance", SUB_TABS), "monitoring");
});
