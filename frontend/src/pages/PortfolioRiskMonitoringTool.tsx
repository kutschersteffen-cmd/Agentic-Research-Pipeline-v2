import { useState } from "react";
import { PortfolioPaneProvider } from "../context/PortfolioPaneContext";
import { PersistentSelectionPane } from "../components/PersistentSelectionPane";
import { MonitoringAlerts } from "./portfolio-monitoring/MonitoringAlerts";
import { CompanyProfiles } from "./portfolio-monitoring/CompanyProfiles";
import { AskThePortfolio } from "./portfolio-monitoring/AskThePortfolio";
import { HoldingsIntake } from "./portfolio-monitoring/HoldingsIntake";
import { openingSubTab, SHOWN_SUB_TABS, SUB_TABS } from "../lib/subTabs";

/** One top-level tool (spec §9): a persistent portfolio/date selection
 * pane that isn't itself a sub-tab, plus one MECE sub-tab per capability
 * area. */
type SendUniverse = (to: "argus" | "transitionPlan", path: string, count: number) => Promise<void> | void;

export function PortfolioRiskMonitoringTool({ initialSub, onSendUniverse }: { initialSub?: string; onSendUniverse?: SendUniverse }) {
  return (
    <PortfolioPaneProvider>
      <Inner initialSub={initialSub} onSendUniverse={onSendUniverse} />
    </PortfolioPaneProvider>
  );
}

type SubId = (typeof SUB_TABS)[number]["id"];

function Inner({ initialSub, onSendUniverse }: { initialSub?: string; onSendUniverse?: SendUniverse }) {
  const [sub, setSub] = useState<SubId>(() => openingSubTab(initialSub));

  return (
    <div className="page">
      <h1>Risk Monitoring</h1>
      <p className="help-text">Pick portfolios and a date. The choice applies to every tab.</p>
      <PersistentSelectionPane onSendUniverse={onSendUniverse} />

      <nav className="sub-nav">
        {SHOWN_SUB_TABS.map((id) => SUB_TABS.find((t) => t.id === id)!).map((t) => (
          <button key={t.id} className={t.id === sub ? "nav-tab active" : "nav-tab"} aria-pressed={t.id === sub} onClick={() => setSub(t.id)}>
            {t.label}
          </button>
        ))}
      </nav>

      {sub === "monitoring" && <MonitoringAlerts />}
      {sub === "profiles" && <CompanyProfiles />}
      {sub === "ask" && <AskThePortfolio />}
      {sub === "holdings" && <HoldingsIntake />}
    </div>
  );
}
