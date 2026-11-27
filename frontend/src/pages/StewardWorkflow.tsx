import { useState, useEffect } from "react";
import { api } from "../api/client";
import { useMe } from "../lib/reviewer";
import { STAGE_TABS } from "./steward/common";
import { DraftingStudio } from "./steward/drafting";
import { WorkbenchStudio } from "./steward/workbench";

export { STAGE_TABS };

/** Which companies the house program covers (see backend stewardship/universe.py). */
function HouseUniverse({ onChanged }: { onChanged: () => void }) {
  const [info, setInfo] = useState<Awaited<ReturnType<typeof api.getHouseUniverse>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reviewer = useMe()?.name ?? "";
  useEffect(() => {
    api.getHouseUniverse().then(setInfo, (e: Error) => setError(e.message));
  }, []);
  async function choose(source: "sample" | "portfolio") {
    setError(null);
    try {
      await api.setHouseUniverse({ source });
      setInfo(await api.getHouseUniverse());
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  if (!info) return error ? <p className="error-text" role="alert">{error}</p> : null;
  return (
    <div className="toolbar">
      <span className="muted">Companies covered:</span>
      {(["sample", "portfolio"] as const).map((s) => (
        <button
          key={s}
          className={info.source === s ? "nav-tab active" : "nav-tab"}
          aria-pressed={info.source === s}
          disabled={!reviewer.trim() && info.source !== s}
          onClick={() => info.source !== s && choose(s)}
        >
          {s === "sample" ? "Synthetic sample" : "Portfolio holdings"}
        </button>
      ))}
      <span className="muted">
        {info.issuers} companies{info.set_by ? ` · set by ${info.set_by}` : ""}
        {!reviewer.trim() && " · enter your name in the user menu (top right) to change it"}
      </span>
      {error && <span className="error-text" role="alert">{error}</span>}
    </div>
  );
}

/** StewardIQ workspace: Selection Workbench and Outreach Drafting. */
export function StewardWorkflow({ initialTab }: { initialTab?: string }) {
  const tab = initialTab === "drafting" ? "drafting" : "workbench";
  const [reloadKey, setReloadKey] = useState(0);
  const bump = () => setReloadKey((k) => k + 1);

  return (
    <div className="steward-page">
      <header className="page-header">
        <h1>StewardIQ</h1>
        <p className="help-text">
          Prioritise companies for engagement, manage programmes and notes, and review outreach drafts with four-eyes approval.
        </p>
        <HouseUniverse onChanged={bump} />
      </header>
      <nav className="tab-bar" aria-label="StewardIQ sections">
        {STAGE_TABS.map((t) => (
          <a
            key={t.id}
            href={`#/stewardship/${t.id}`}
            className={tab === t.id ? "nav-tab active" : "nav-tab"}
            aria-current={tab === t.id ? "page" : undefined}
          >
            {t.label}
          </a>
        ))}
      </nav>
      {tab === "workbench" && <WorkbenchStudio key={reloadKey} />}
      {tab === "drafting" && <DraftingStudio key={reloadKey} />}
    </div>
  );
}
