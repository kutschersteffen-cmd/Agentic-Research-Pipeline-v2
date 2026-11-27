import type { EngagementIssue } from "../types";

export interface EngagementCounts {
  open: number;
  stalled: number;
  escalated: number;
}

/** Open (open or stalled), stalled, and escalated past private engagement while not resolved or closed. */
export function engagementCounts(records: { issues: Pick<EngagementIssue, "status" | "escalation_stage">[] }[]): EngagementCounts {
  const issues = records.flatMap((r) => r.issues);
  return {
    open: issues.filter((i) => i.status === "open" || i.status === "stalled").length,
    stalled: issues.filter((i) => i.status === "stalled").length,
    escalated: issues.filter((i) => i.escalation_stage !== "private_engagement" && i.status !== "resolved" && i.status !== "closed").length,
  };
}

/** The start page's engagement line: `null` while loading (unknown, never zero), "error" when the load failed. */
export function engagementLine(counts: EngagementCounts | null | "error"): string {
  if (counts === "error") return "Engagement · counts unavailable";
  const n = (k: keyof EngagementCounts) => (counts ? String(counts[k]) : "—");
  return `Engagement · ${n("open")} open · ${n("stalled")} stalled · ${n("escalated")} escalated`;
}

/** The trigger scan's note on signals whose company is not in the scanned list (they are skipped). */
export function unlistedText(count: number, ids: string[]): string {
  return count === 1
    ? `1 signal skipped: its company is not in the list (${ids.join(", ")}).`
    : `${count} signals skipped: their companies are not in the list (${ids.join(", ")}).`;
}

const DEMO_SOURCES = ["mock_voice_seed", "npx_urth_demo"];

/** An objective is demo data when it, or the issue it sits under, came from a demo seed (`Demo data` label). */
export function isDemo(issue: Pick<EngagementIssue, "data_source">, objective: { source?: string | null }): boolean {
  return DEMO_SOURCES.includes(issue.data_source ?? "") || DEMO_SOURCES.includes(objective.source ?? "");
}

/** The issue header's `Demo data` chip: the issue, or any of its objectives, came from a demo seed. */
export function isDemoIssue(issue: Pick<EngagementIssue, "data_source" | "objectives">): boolean {
  return isDemo(issue, {}) || issue.objectives.some((o) => isDemo(issue, o));
}

/** A code as words: `in_progress` -> `in progress`. */
export function fmt(s: string): string {
  return s.replace(/_/g, " ");
}

/** A due date as stored, or only its date when it is an ISO timestamp (`2026-12-31T00:00:00` -> `2026-12-31`). */
export function dueText(date: string): string {
  return /^\d{4}-\d{2}-\d{2}T/.test(date) ? date.slice(0, 10) : date;
}

/** The "Approve N routine" dialog's flag list: `<company>: <message>` for each watch flag of a company in the batch, once. */
export function batchFlagLines(ballots: { company_id: string; name: string; watch_flags?: { message: string }[] }[], companyIds: string[]): string[] {
  const lines = ballots.filter((b) => companyIds.includes(b.company_id)).flatMap((b) => (b.watch_flags ?? []).map((f) => `${b.name}: ${f.message}`));
  return [...new Set(lines)];
}
