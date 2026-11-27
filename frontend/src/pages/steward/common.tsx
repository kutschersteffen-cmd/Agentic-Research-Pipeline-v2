import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import { SignedInAs } from "../../components/SignedInAs";
import { useMe } from "../../lib/reviewer";
import type { StewardPolicyId, StewardPolicyInfo } from "../../types";

export function fmt(v: unknown): string {
  if (v === null || v === undefined) return "not set";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "object") return Object.entries(v as Record<string, unknown>).map(([k, x]) => `${k}: ${fmt(x)}`).join(", ");
  return String(v);
}

export const words = (s: string) => s.replace(/_/g, " ");

export const STAGE_TABS = [
  { id: "workbench", label: "Workbench" },
  { id: "drafting", label: "Drafting" },
] as const;

/** The signed-in user's name, or "" when signed out. The server records who decided. */
export const useActor = (): string => useMe()?.name ?? "";

export function ActorField() {
  return (
    <div className="actor-field">
      <SignedInAs compact />
    </div>
  );
}

export function DataTable({ rows, empty = "Nothing to show." }: { rows: Record<string, unknown>[]; empty?: string }) {
  if (rows.length === 0) return <p className="muted">{empty}</p>;
  const keys = Object.keys(rows[0]);
  return (
    <div className="table-wrap">
      <table className="data-table stack-on-phone">
        <thead>
          <tr>
            {keys.map((k) => (
              <th key={k}>{words(k)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {keys.map((k) => (
                <td key={k} data-label={words(k)}>{typeof row[k] === "string" ? words(row[k] as string) : fmt(row[k])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A studio section: one step of review, design, calibration or versions. */
export function Section({ step, title, children, planned }: { step: string; title: string; children: ReactNode; planned?: boolean }) {
  return (
    <section className={`card studio-section${planned ? " planned" : ""}`}>
      <p className="studio-step">{step}</p>
      <h2>
        {title}
        {planned && <span className="chip chip-not-built">Not built yet</span>}
      </h2>
      {children}
    </section>
  );
}

/** The rule editor (design, preview, versions) stays folded until someone means to change the rules. */
export function RuleEditor({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const openRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) openRef.current?.focus();
  }, [open]);
  if (!open) {
    return (
      <section className="card rule-editor-closed">
        <button className="secondary" aria-expanded={false} onClick={() => setOpen(true)}>
          Edit {label}…
        </button>
        <span className="muted">Change the rules, preview the effect against the active ones, then save a version.</span>
      </section>
    );
  }
  return (
    <div ref={openRef} tabIndex={-1} className="rule-editor-open" aria-label={`${label} editor`} role="region">
      <div className="toolbar rule-editor-bar">
        <button className="secondary" aria-expanded onClick={() => setOpen(false)}>
          Close the {label} editor
        </button>
      </div>
      {children}
    </div>
  );
}

export function usePolicy(policyId: StewardPolicyId) {
  const [info, setInfo] = useState<StewardPolicyInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(async () => {
    try {
      setInfo(await api.getStewardPolicy(policyId));
    } catch (err) {
      setError((err as Error).message);
    }
  }, [policyId]);
  useEffect(() => {
    reload();
  }, [reload]);
  return { info, error, reload };
}

/** Save the working copy as a new version; activate any version with a named approver. */
export function VersionsPanel({
  policyId,
  info,
  workingCopy,
  dirty,
  invalid,
  actor,
  onSaved,
  onLoad,
  onActivated,
}: {
  policyId: StewardPolicyId;
  info: StewardPolicyInfo;
  workingCopy: unknown;
  dirty: boolean;
  /** Why the working copy cannot be saved (e.g. weights that do not add up), if it cannot. */
  invalid?: string;
  actor: string;
  onSaved: () => void;
  onLoad: (version: number) => void;
  onActivated: () => void;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const needName = actor ? undefined : "Sign in above first";

  async function save() {
    setBusy("save");
    setError(null);
    setMessage(null);
    try {
      const res = await api.saveStewardPolicyVersion(policyId, { content: workingCopy, note });
      setNote("");
      setMessage(`Saved as version ${res.version}. It is not active until someone activates it.`);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }
  async function activate(version: number) {
    setBusy(`activate-${version}`);
    setError(null);
    setMessage(null);
    try {
      await api.activateStewardPolicy(policyId, { version });
      setMessage(`Version ${version} is now active.`);
      onActivated();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }
  const lastActivation = (v: number) => [...info.activations].reverse().find((a) => a.version === v);

  return (
    <>
      <p className="help-text">
        Saving checks that the configuration runs and stores it as a new, unchangeable version. It only takes effect once a second person
        (not its author) activates it; every activation is logged, so you can always roll back.
      </p>
      <div className="inline-fields decision-controls">
        <input aria-label="Version note" placeholder="What changed and why" value={note} onChange={(e) => setNote(e.target.value)} />
        <button onClick={save} disabled={!actor || !dirty || !!invalid || busy !== null} title={needName ?? invalid ?? (dirty ? undefined : "No changes to save")}>
          {busy === "save" ? "Saving…" : "Save as new version"}
        </button>
      </div>
      {message && <p className="status-text">{message}</p>}
      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Version</th>
              <th>Note</th>
              <th>Created</th>
              <th>Status</th>
              <th>
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {[...info.versions].reverse().map((v) => {
              const active = v.version === info.active_version;
              const act = lastActivation(v.version);
              return (
                <tr key={v.version} className={active ? "selected-row" : undefined}>
                  <td>v{v.version}</td>
                  <td>{v.note || "—"}</td>
                  <td>
                    {v.created_by}
                    {v.created_at ? ` · ${new Date(v.created_at).toLocaleDateString()}` : ""}
                  </td>
                  <td>
                    {active ? <strong>active</strong> : "inactive"}
                    {act ? <span className="muted"> · approved by {act.approved_by}</span> : null}
                  </td>
                  <td>
                    <div className="row-actions">
                      <button className="link-button" onClick={() => onLoad(v.version)}>
                        Load into editor
                      </button>
                      {!active && (
                        <button
                          onClick={() => activate(v.version)}
                          disabled={!actor || busy !== null || v.created_by.toLowerCase() === actor.toLowerCase()}
                          title={needName ?? (v.created_by.toLowerCase() === actor.toLowerCase() ? "Four-eyes: someone other than the author must activate" : undefined)}
                        >
                          {busy === `activate-${v.version}` ? "Activating…" : "Activate"}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
