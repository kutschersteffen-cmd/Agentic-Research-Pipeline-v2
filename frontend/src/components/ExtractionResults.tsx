import { Fragment, useEffect, useState } from "react";
import { CompanyLink } from "./CompanyLink";
import { api } from "../api/client";
import { ConfidenceBadge, GroundedBadge } from "./ConfidenceBadge";
import { ReviewControls } from "./ReviewControls";
import { CitationList } from "./CitationList";
import type { ActiveSource } from "./SourcePanel";
import type { ExtractedField, ExtractionRecord, ReviewDecision, ReviewStates } from "../types";
import { fieldItemKey } from "../lib/reviewKeys";
import { correctionLine, recordFieldNames } from "../lib/corrections";
import { failedChecks, routeLabel, valueLabel, withEditedValue } from "../lib/fieldValue";
import { TRIAL_TITLE } from "../lib/runs";
import { activatable } from "../lib/activatable";
import { notesInWords } from "../lib/routeReasons";
import { ProposedTag } from "./ProposedTag";
import { WalkthroughLink } from "./WalkthroughLink";
import { rowWalkthroughHref } from "../lib/walkthrough";
import { OriginTag } from "./ReviewTiles";
import { editedText, matchesTile, type ReviewTileCounts } from "../lib/stagedFlow";

type TileFilter = keyof ReviewTileCounts | null;
const NO_MATCH = <p className="muted">No items match this filter.</p>;

export function FieldDetail({ field, fieldNames = {}, walkthroughHref, onOpenSource }: { field: ExtractedField; fieldNames?: Record<string, string>; walkthroughHref?: string; onOpenSource: (s: ActiveSource) => void }) {
  return (
    <div className="field-detail">
      <strong>{field.field_name}:</strong> {valueLabel(field)}{" "}
      <ConfidenceBadge value={field.confidence} /> <GroundedBadge grounded={field.grounded} />
      {(field.period_end || field.period_start) && (
        <p className="muted">Period: {field.period_start ? `${field.period_start} to ` : "to "}{field.period_end ?? "—"}{field.basis ? ` (${field.basis})` : ""}</p>
      )}
      {field.canonical_value != null && String(field.canonical_value) !== String(field.value) && (
        <p className="muted">≈ {field.canonical_value} {field.canonical_unit ?? ""}</p>
      )}
      {field.qualifiers?.map((q) => <span key={q} className="badge">{q}</span>)}
      {routeLabel(field) && <p><span className={`badge ${field.route === "hold" ? "badge-low" : "badge-mid"}`}>{routeLabel(field)}</span></p>}
      {failedChecks(field).map((c) => (
        <p key={c.check_id}><span className={`badge ${c.severity === "block" ? "badge-low" : "badge-mid"}`}>{c.check_id}: {c.detail}</span></p>
      ))}
      {field.fx_rate_ref && <p className="muted">FX: {field.fx_rate_ref}</p>}
      {field.corrections?.map((c, i) => <p key={i} className="muted">{correctionLine(c, (id) => fieldNames[id] ?? id)}</p>)}
      {field.verifier_notes && <p className="muted">{notesInWords(field.verifier_notes)}</p>}
      <CitationList citations={field.citations} onOpenSource={onOpenSource} />
      {walkthroughHref && <WalkthroughLink href={walkthroughHref} />}
    </div>
  );
}

/** company_id to the central id each company of the run was matched to (its company link opens that record). */
function useCentralIds(runId: string): Record<string, string> {
  const [ids, setIds] = useState<Record<string, string>>({});
  useEffect(() => {
    let live = true; // an answer for a run no longer shown must not overwrite the current one
    setIds({});
    api.getRunCompanies(runId).then(
      (r) => live && setIds(Object.fromEntries(r.companies.flatMap((c) => (c.entity_id ? [[c.company_id, c.entity_id]] : [])))),
      () => live && setIds({}), // unreadable: the links fall back to the universe id
    );
    return () => {
      live = false;
    };
  }, [runId]);
  return ids;
}

interface ExtractionResultsTableProps {
  results: ExtractionRecord[];
  runId: string;
  expanded: string | null;
  onToggleExpanded: (companyId: string) => void;
  reviewDecisions: Record<string, ReviewDecision>;
  /** Every decided field's review state, from the same `review-decisions` response. */
  states: ReviewStates;
  reviewer: string;
  onReviewDone: () => void;
  onOpenSource: (s: ActiveSource) => void;
  filter?: TileFilter;
  /** The run was a trial (draft schema fields): mark its results as not final. */
  trial?: boolean;
}

export function ExtractionResultsTable({
  results,
  runId,
  expanded,
  onToggleExpanded,
  reviewDecisions,
  states,
  reviewer,
  onReviewDone,
  onOpenSource,
  filter = null,
  trial = false,
}: ExtractionResultsTableProps) {
  const central = useCentralIds(runId);
  if (results.length === 0) return null;
  // Items are fields; a field is flagged when its record needs review.
  const shownFields = (r: ExtractionRecord) =>
    r.fields.filter((f) => matchesTile(filter, r.needs_review, reviewDecisions[fieldItemKey(r, f)]));
  const shown = results.filter((r) => shownFields(r).length > 0);
  if (shown.length === 0) return NO_MATCH;
  return (
    <div className="table-wrap">
      {trial && (
        <p className="await-text">
          <span className="badge badge-mid">trial</span> {TRIAL_TITLE}
        </p>
      )}
      <table className="data-table">
        <thead>
          <tr>
            <th>Company</th>
            <th>Fields</th>
            <th>Overall confidence</th>
            <th>Needs review</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => {
            const names = recordFieldNames(r);
            return (
            <Fragment key={r.company_id}>
              <tr className="clickable-row" {...activatable(() => onToggleExpanded(r.company_id), expanded === r.company_id)}>
                <td><CompanyLink companyId={r.company_id} entityId={central[r.company_id]}>{r.name}</CompanyLink> {r.ticker && <span className="muted">({r.ticker})</span>}</td>
                <td>{r.fields.map((f) => `${f.field_name}${f.period_end ? ` (${f.period_end})` : ""}=${editedText(reviewDecisions[fieldItemKey(r, f)]) ?? valueLabel(f)}`).join(", ")}</td>
                <td><ConfidenceBadge value={r.overall_confidence} /></td>
                <td>{r.needs_review ? <ProposedTag /> : ""}</td>
              </tr>
              {expanded === r.company_id && (
                <tr>
                  <td colSpan={4} className="detail-cell">
                    {r.held_documents?.map((h) => (
                      <p key={h.doc_id} className="muted">Held: {h.title} (covers {h.covered_entity})</p>
                    ))}
                    {shownFields(r).map((f) => {
                      const itemKey = fieldItemKey(r, f);
                      const d = reviewDecisions[itemKey];
                      return (
                        <div key={`${f.field_id}:${f.period_end ?? ""}`}>
                          <FieldDetail field={editedText(d) === undefined ? f : withEditedValue(f, editedText(d)!)} fieldNames={names} walkthroughHref={rowWalkthroughHref(runId, r, f)} onOpenSource={onOpenSource} />
                          <OriginTag decision={d} systemValue={valueLabel(f)} />
                          {f.route !== "hold" && (
                            <ReviewControls
                              runId={runId}
                              itemKey={itemKey}
                              reviewer={reviewer}
                              onDone={onReviewDone}
                              item={{
                                kind: "value",
                                state: states[itemKey]?.state ?? "pending",
                                escalated: states[itemKey]?.escalated ?? false,
                                decision: d ?? null,
                              }}
                              onOpenSource={onOpenSource}
                            />
                          )}
                        </div>
                      );
                    })}
                  </td>
                </tr>
              )}
            </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
