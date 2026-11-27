import test from "node:test";
import assert from "node:assert/strict";
import { batchFlagLines, dueText, engagementCounts, engagementLine, fmt, isDemoIssue } from "../src/lib/engagement.ts";

const issue = (status: string, escalation_stage: string) => ({ status, escalation_stage }) as never;

test("engagementCounts tells open, stalled and escalated apart", () => {
  const records = [
    {
      issues: [
        issue("open", "private_engagement"),
        issue("open", "written_escalation_to_board"),
        issue("stalled", "written_escalation_to_board"),
        issue("resolved", "written_escalation_to_board"),
        issue("closed", "written_escalation_to_board"),
      ],
    },
  ];
  const counts = engagementCounts(records);
  assert.deepEqual(counts, { open: 3, stalled: 1, escalated: 2 });
  assert.equal(engagementLine(counts), "Engagement · 3 open · 1 stalled · 2 escalated");
});

test("engagementCounts is all zero with no records or no issues", () => {
  assert.deepEqual(engagementCounts([]), { open: 0, stalled: 0, escalated: 0 });
  assert.deepEqual(engagementCounts([{ issues: [] }]), { open: 0, stalled: 0, escalated: 0 });
});

test("an unknown escalation stage counts as escalated while the issue is open", () => {
  assert.deepEqual(engagementCounts([{ issues: [issue("open", "some_new_stage")] }]), { open: 1, stalled: 0, escalated: 1 });
});

test("engagementLine never shows a zero nobody measured", () => {
  assert.equal(engagementLine(null), "Engagement · — open · — stalled · — escalated");
  assert.equal(engagementLine("error"), "Engagement · counts unavailable");
});

// Stewardship screens polish (spec stewardship-screens-polish, PR B).

test("dueText keeps a date whole unless it is an ISO timestamp (B2)", () => {
  assert.equal(dueText("end of FY2027"), "end of FY2027");
  assert.equal(dueText("2026-12-31T00:00:00"), "2026-12-31");
  assert.equal(dueText("2025-12-31 (approx.)"), "2025-12-31 (approx.)");
});

test("fmt turns codes into words (B9)", () => {
  assert.equal(fmt("not_achieved"), "not achieved");
  assert.equal(fmt("in_progress"), "in progress");
});

test("isDemoIssue looks at the issue and every objective (B10)", () => {
  assert.equal(isDemoIssue({ data_source: null, objectives: [{ source: null }, { source: "mock_voice_seed" }] as never }), true);
  assert.equal(isDemoIssue({ data_source: "npx_urth_demo", objectives: [] }), true);
  assert.equal(isDemoIssue({ data_source: null, objectives: [{ source: null }] as never }), false);
});

test("batchFlagLines lists each flag of a company in the batch once (B11)", () => {
  const ballots = [
    { company_id: "A", name: "Alpha Corp", watch_flags: [{ message: "Commitment overdue." }, { message: "Objective overdue." }] },
    { company_id: "A", name: "Alpha Corp", watch_flags: [{ message: "Commitment overdue." }] },
    { company_id: "B", name: "Beta plc", watch_flags: [] },
    { company_id: "C", name: "Gamma", watch_flags: [{ message: "Broken." }] },
  ];
  assert.deepEqual(batchFlagLines(ballots, ["A", "A", "B"]), ["Alpha Corp: Commitment overdue.", "Alpha Corp: Objective overdue."]);
  assert.deepEqual(batchFlagLines(ballots, ["B"]), []);
});
