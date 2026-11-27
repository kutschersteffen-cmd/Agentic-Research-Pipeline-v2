// Showcase fixes, R&D Lab screens (spec showcase-themes-fixes, PR 2): what the pages label and link.
import { test } from "node:test";
import assert from "node:assert/strict";
import { NO_MODEL_CALLS, progressUnit, spentNothing } from "../src/lib/runs.ts";
import { intervalError, NO_COMPANIES, NOVELTY_HELP, SCANNING, scanActive } from "../src/lib/emergingThemes.ts";
import { stepLinkText } from "../src/lib/dossiers.ts";
import { reviewHref, type PlanCall } from "../src/lib/plans.ts";
import { companies } from "../src/lib/themeBuilder.ts";

test("an emerging-themes scan counts mentions, other runs companies", () => {  // AC-50, AC-98
  assert.equal(progressUnit("emerging_themes"), "mentions");
  assert.equal(progressUnit("theme"), "companies");
});

test("a finished run without tokens says so instead of $0.00", () => {  // AC-81
  assert.equal(spentNothing({ status: "completed", input_tokens: 0, output_tokens: 0 }), true);
  assert.equal(spentNothing({ status: "running", input_tokens: 0, output_tokens: 0 }), false);
  assert.equal(spentNothing({ status: "completed", input_tokens: 1, output_tokens: 0 }), false);
  assert.equal(NO_MODEL_CALLS, "No new model calls (answers reused or nothing to read)");
});

test("Emerging Themes wording", () => {  // AC-53, AC-55, AC-56
  assert.equal(SCANNING, "Scanning… candidates appear when the scan finishes.");
  assert.equal(NOVELTY_HELP, "How different this cluster is from themes in earlier scans. 100% on a first scan.");
  assert.equal(NO_COMPANIES, "None in your universe");
  assert.deepEqual(["running", "pending", "completed", undefined].map(scanActive), [true, true, false, false]);
});

test("the schedule refuses an interval below 1 hour before sending", () => {  // AC-58
  for (const h of [0, 0.5, -1, NaN]) assert.equal(intervalError(h), "Enter an interval of at least 1 hour.");
  assert.equal(intervalError(1), null);
  assert.equal(intervalError(24), null);
});

test("step 4 waiting on review links to the review", () => {  // AC-61
  assert.equal(stepLinkText(4, "#/review/theme/r1"), "Review the open items");
  assert.equal(stepLinkText(4, "#/theme/r1"), "Open the run");
});

const call = (over: Partial<PlanCall>): PlanCall => ({
  seq: 1, kind: "extraction", params: {}, status: "awaiting_review", run_id: "r", result_ref: null, ...over,
});

test("a step waiting for review links to where it is reviewed", () => {  // AC-62, AC-63, AC-64, AC-128
  assert.equal(reviewHref(call({ run_id: "r_1" })), "#/review/extraction/r_1");
  assert.equal(reviewHref(call({ kind: "universe_build" })), "#/review/theme/r");
  assert.equal(reviewHref(call({ kind: "document_discovery" })), "#/review/discovery/r");
  assert.equal(reviewHref(call({ kind: "financials_extraction" })), "#/review/financials/r");
  assert.equal(reviewHref(call({ kind: "report_render", run_id: null, result_ref: "report:7" })), "#/reporting");
  assert.equal(reviewHref(call({ kind: "xbrl_facts" })), null);
});

test("one company is singular", () => {  // AC-80, AC-99, AC-126
  assert.deepEqual([companies(1), companies(2)], ["1 company", "2 companies"]);
});
