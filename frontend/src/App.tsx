import { Suspense, useEffect, useRef, useState } from "react";
import { HashRouter, useLocation, useNavigate } from "react-router-dom";
import { canLeave } from "./lib/leaveGuard";
import { ProcessBar, StartPage, WorkspaceOverview } from "./pages/ProcessHub";
import { singleFlight, stepFromUrl } from "./lib/argusFlow";
import { WORKSPACES, workspaceOfProcess, type WorkspaceId } from "./lib/processes";
import { STAGE_TABS } from "./pages/steward/common";
import { SUB_TABS as RISK_TABS } from "./lib/subTabs";
import { CommandPalette } from "./components/CommandPalette";
import { runItem, type PaletteItem } from "./lib/commandPalette";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ctrlJTarget, rfpId, type Selection } from "./lib/agent";
import { useMe } from "./lib/reviewer";
import { AppTopbar } from "./components/AppTopbar";
import { WorkspaceRow } from "./components/WorkspaceRow";
import type { ReviewableRunKind, RunManifest, WaitingCounts } from "./types";
import { REVIEWABLE_RUN_TYPES } from "./lib/runs";
import { api } from "./api/client";
import { listAllRuns } from "./lib/poll";
import { HUBS, entryTab, redirectHash, safeDecode } from "./lib/nav";
import { Landing } from "./pages/Landing";
import { ArgusFlow, ArgusNew, ArgusStart, ArgusWalkthrough, openNewFlow } from "./features/argus";
import {
  EngagementDashboard,
  PortfolioRiskMonitoringTool,
  ReportBuilder,
  RfpAnswers,
  StewardWorkflow,
} from "./features/stewardiq";
import { TransitionBarrierAssessment } from "./features/transition";
import {
  AuthorityTaxonomyRun,
  DesignStrategy,
  EmergingThemesDetector,
  TaxonomyLibrary,
  ThemeBuilder,
  ThemeDossiers,
  ValueChainExplorer,
} from "./features/rd_lab";
import { Company, DataLibrary, Feeds, Issues, Outputs, Search, SecurityMaster, SmartSearch } from "./features/data_hub";
import { Agent, BackgroundAgents, ReviewQueue, RunHistory } from "./features/agent";

const TABS = [
  { id: "home", label: "Start" },
  { id: "stewardiq", label: "StewardIQ" },
  { id: "argus", label: "Argus" },
  { id: "argusWalkthrough", label: "Walkthrough" },
  { id: "transitionIntel", label: "Transition Intel" },
  { id: "rdLab", label: "R&D Lab" },
  { id: "dataHub", label: "Data Hub" },
  { id: "search", label: "Search" },
  { id: "securityMaster", label: "Security Master" },
  { id: "feeds", label: "Feeds" },
  { id: "issues", label: "Issues" },
  { id: "smartSearch", label: "Smart Search" },
  { id: "outputs", label: "Outputs" },
  { id: "theme", label: "Thematic Universe" },
  { id: "taxonomy", label: "Taxonomy Library" },
  { id: "emergingThemes", label: "Emerging Themes" },
  { id: "themes", label: "Theme dossiers" },
  { id: "designStrategy", label: "Build a thematic portfolio" },
  { id: "backgroundAgents", label: "Background Agents" },
  { id: "transitionBarrier", label: "Transition Barriers" },
  { id: "portfolio-monitoring", label: "Risk Monitoring" },
  { id: "review", label: "Needs you" },
  { id: "history", label: "Run History" },
  { id: "agent", label: "Agent" },
  { id: "stewardship", label: "Steward Workflow" },
  { id: "engagement", label: "Engagement" },
  { id: "reporting", label: "Presentations & Reports" },
  { id: "valueChain", label: "Value Chain Explorer" },
  { id: "rfp", label: "RFP Answers" },
  { id: "library", label: "Data Library" },
  // Reached from company names elsewhere (#/companies/<ref>) and the palette; not in the sidebar.
  { id: "companies", label: "Company" },
] as const;

type TabId = (typeof TABS)[number]["id"];

const hubOf = (id: TabId) => HUBS.find((h) => h.tabs.some(([t]) => t === id));
const isWorkspace = (id: string): id is WorkspaceId => WORKSPACES.some((w) => w.id === id);

// Everything the command palette can jump to: every screen (under its hub's
// name where it has one), plus the Steward stages and Risk Monitoring tabs.
const PALETTE_ITEMS: PaletteItem[] = [
  ...TABS.map((t) => ({ label: t.label, hint: hubOf(t.id)?.label.replace(t.label, "") || undefined, href: `#/${t.id}` })),
  ...STAGE_TABS.map((t) => ({ label: t.label, hint: "Steward Workflow", href: `#/stewardship/${t.id}` })),
  ...RISK_TABS.map((t) => ({ label: t.label, hint: "Risk Monitoring", href: `#/portfolio-monitoring/${t.id}` })),
  { label: "Refine a document", hint: "Agent", href: "#/agent/refine" },
];

/** The URL is the source of truth for where you are: `#/<tab>/<param>...`,
 * so refresh, Back and a pasted link all land on the same view -- e.g.
 * `#/review/extraction/<run id>`. */
function parsePath(pathname: string): { tab: TabId; params: string[] } {
  const [tab, ...params] = pathname.replace(/^\/?/, "").split("/").filter(Boolean).map(safeDecode);
  // Old links: the Theme Machine and Design Studio boxes merged into R&D Lab;
  // the Processes screen's processes now live on their workspace pages.
  if (tab === "themeMachine" || tab === "designStudio") return { tab: "rdLab", params: [] };
  if (tab === "processes") return { tab: workspaceOfProcess(params[0])?.id ?? "home", params: [] };
  return TABS.some((t) => t.id === tab) ? { tab: tab as TabId, params } : { tab: "home", params: [] };
}

/** `#/agent/<plan_id>` selects a plan, `#/agent/ask/<thread_id>` an ask thread, `#/agent/exploration/<id>` an
 * exploration, `#/agent/refine/<kind>/<doc_id>` a Refine thread and `#/agent/refine` the Refine picker. */
function agentSelection(params: string[]): Selection {
  if (params[0] === "refine") return { kind: "refine", id: params[1] && params[2] ? `${params[1]}/${params[2]}` : "" };
  if (params[0] === "ask" || params[0] === "exploration") return params[1] ? { kind: params[0], id: params[1] } : null;
  return params[0] ? { kind: "plan", id: params[0] } : null;
}

/** The address params of an Agent selection (the inverse of agentSelection). */
function agentParams(s: NonNullable<Selection>): string[] {
  if (s.kind === "plan") return [s.id];
  if (s.kind === "refine") return s.id ? ["refine", s.id.slice(0, s.id.indexOf("/")), s.id.slice(s.id.indexOf("/") + 1)] : ["refine"];
  return [s.kind, s.id];
}

function buildPath(tab: TabId, ...params: string[]) {
  return "/" + [tab, ...params].map(encodeURIComponent).join("/");
}

function App() {
  const location = useLocation();
  const routerNavigate = useNavigate();
  const initialTarget = redirectHash(`#${location.pathname}`);
  const initialPath = initialTarget ? initialTarget.slice(1) : location.pathname;
  const [route, setRoute] = useState(() => parsePath(initialPath));
  const active = route.tab;
  const [waiting, setWaiting] = useState<WaitingCounts | null>(null);
  const [recentRuns, setRecentRuns] = useState<RunManifest[]>([]);
  const [pendingTaxonomyId, setPendingTaxonomyId] = useState<string | null>(null);

  const navigate = (tab: TabId, ...params: string[]) => routerNavigate(buildPath(tab, ...params));

  // The pathname last shown, so a navigation the open screen refuses can be put back.
  const shownPath = useRef(initialPath);
  useEffect(() => {
    const target = redirectHash(`#${location.pathname}`);
    if (target) {
      routerNavigate(target.slice(1), { replace: true });
      return;
    }
    if (location.pathname === shownPath.current) return;
    // Any change of address remounts a guarded screen (its key is its params), so even a link to the same tab asks.
    if (!canLeave()) {
      routerNavigate(shownPath.current, { replace: true });
      setAgentAsk(null); // a refused move to the Agent screen must not leave its question queued
      return;
    }
    shownPath.current = location.pathname;
    setRoute(parsePath(location.pathname));
    window.scrollTo(0, 0);
  }, [location.pathname, routerNavigate]);

  // An announcement belongs to the screen it was made on: another screen starts with an empty live region.
  useEffect(() => {
    const el = document.getElementById("announcer");
    if (el) el.textContent = "";
  }, [active]);

  // A decision anywhere (see lib/announce) refreshes the counts below.
  const [decidedAt, setDecidedAt] = useState(0);
  useEffect(() => {
    const onDecided = () => setDecidedAt(Date.now());
    window.addEventListener("arp:decided", onDecided);
    return () => window.removeEventListener("arp:decided", onDecided);
  }, []);

  // Counts on the "Needs you" items, refreshed on every navigation and after
  // every decision. Failure leaves them off rather than showing a zero nobody measured.
  useEffect(() => {
    api.getWaiting().then(setWaiting, () => setWaiting(null));
    listAllRuns()
      .then((runs) => setRecentRuns([...runs].sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1)).slice(0, 50)))
      .catch(() => {});
  }, [route, decidedAt]);

  const hub = hubOf(active);
  // The tab title names the screen, for browser tabs and screen readers.
  useEffect(() => {
    document.title = `${hub?.label ?? TABS.find((t) => t.id === active)!.label} · ARP`;
  }, [active, hub]);

  const pendingReview =
    active === "review" && route.params.length === 2 && REVIEWABLE_RUN_TYPES.has(route.params[0])
      ? { kind: route.params[0] as ReviewableRunKind, runId: route.params[1] }
      : null;

  const [paletteOpen, setPaletteOpen] = useState(false);
  const me = useMe();
  const canAsk = me != null && me.role !== "viewer";
  // Ask ARP lives on the Agent screen: Ctrl/⌘J focuses its composer, the palette's ask sends a new ask thread there.
  const [agentFocus, setAgentFocus] = useState(0);
  const [agentAsk, setAgentAsk] = useState<{ id: number; question: string } | null>(null);
  // The palette's ask and a workspace's Ask ARP box send a new ask thread on the Agent screen.
  const askAgent = (question: string) => { setAgentAsk({ id: Date.now(), question }); navigate("agent"); };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen(true);
      }
      const target = ctrlJTarget(canAsk);
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "j" && target) {
        e.preventDefault();
        routerNavigate(target.replace(/^#/, ""));
        setAgentFocus(Date.now());
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [canAsk, routerNavigate]);
  function go(id: TabId) {
    navigate(id);
  }

  // A hand-over opens step 1 of a new Argus flow with the companies listed; the Transition Plan one also picks that template.
  // One hand-over at a time: a double click on "Argus →" must not start two flows.
  const sendToArgus = useRef(singleFlight((to: "argus" | "transitionPlan", path: string) =>
    openNewFlow({ universePath: path, preset: to === "transitionPlan" ? "transition_plan" : null }))).current;

  function sendToTheme(taxonomyId: string) {
    setPendingTaxonomyId(taxonomyId);
    navigate("theme");
  }

  function openReview(kind: ReviewableRunKind, runId: string) {
    navigate("review", kind, runId);
  }

  return (
    <div className="app-shell app-shell-start">
      {/* Routing lives in the hash, so the skip link focuses <main> instead of
          following an in-page anchor. */}
      <a
        className="skip-link"
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Skip to content
      </a>
      <div id="announcer" className="visually-hidden" role="status" aria-live="polite" />
      <AppTopbar
        active={active}
        canAsk={canAsk}
        waiting={waiting}
        onSearch={() => setPaletteOpen(true)}
      />
      <WorkspaceRow hash={`#${location.pathname}`} />
      {paletteOpen && (
        <CommandPalette
          items={[...PALETTE_ITEMS, ...recentRuns.map(runItem)]}
          onClose={() => setPaletteOpen(false)}
          onAsk={canAsk ? askAgent : undefined}
        />
      )}
      <main className="app-main" id="main" tabIndex={-1}>
        <ProcessBar tab={active} sub={route.params[0]} />
        {hub && (
          <nav className="sub-nav hub-nav" aria-label={hub.label}>
            {hub.tabs.map(([id, label]) => (
              <a key={id} href={`#/${id}`} className={id === active ? "nav-tab active" : "nav-tab"} aria-current={id === active ? "page" : undefined}>
                {label}
              </a>
            ))}
          </nav>
        )}
        <ErrorBoundary key={location.pathname}>
        <Suspense fallback={<p className="muted" role="status">Loading…</p>}>
        {active === "home" && <StartPage />}
        {active === "argus" && route.params[0] === "new" && <ArgusNew preset={route.params[1] ?? null} />}
        {active === "argus" && route.params[0] !== "new" && (route.params[0] ? <ArgusFlow key={route.params[0]} flowId={route.params[0]} step={stepFromUrl(route.params[1])} /> : <ArgusStart />)}
        {isWorkspace(active) && active !== "argus" && <WorkspaceOverview key={active} id={active} onAsk={canAsk ? askAgent : undefined} />}
        {active === "search" && <Search />}
        {active === "securityMaster" && <SecurityMaster />}
        {active === "feeds" && <Feeds />}
        {active === "issues" && <Issues />}
        {active === "smartSearch" && <SmartSearch />}
        {active === "outputs" && <Outputs />}
        {active === "theme" && <ThemeBuilder key={route.params[0]} initialRunId={route.params[0] ?? null} onSendToArgus={(path) => sendToArgus("argus", path)} pendingTaxonomyId={pendingTaxonomyId} onPendingTaxonomyTaken={() => setPendingTaxonomyId(null)} />}
        {active === "taxonomy" && route.params[0] === "authority" && <AuthorityTaxonomyRun key={route.params[1] ?? "new"} runId={route.params[1]} />}
        {active === "taxonomy" && route.params[0] !== "authority" && <TaxonomyLibrary onUseInTheme={sendToTheme} />}
        {active === "emergingThemes" && <EmergingThemesDetector onNavigate={go} />}
        {active === "designStrategy" && <DesignStrategy />}
        {active === "themes" && <ThemeDossiers params={route.params} onFindCompanies={sendToTheme} />}
        {active === "backgroundAgents" && <BackgroundAgents />}
        {active === "transitionBarrier" && <TransitionBarrierAssessment params={route.params} />}
        {active === "portfolio-monitoring" && <PortfolioRiskMonitoringTool key={route.params[0]} initialSub={route.params[0]} onSendUniverse={sendToArgus} />}
        {active === "review" && <ReviewQueue key={pendingReview ? `${pendingReview.kind}/${pendingReview.runId}` : "review"} pendingReview={pendingReview} waiting={waiting} />}
        {active === "history" && <RunHistory onOpenReview={openReview} focusRunId={route.params[0] ?? null} />}
        {active === "agent" && (
          <Agent selected={agentSelection(route.params)} canAsk={canAsk} focusToken={agentFocus} pendingAsk={agentAsk}
            onPendingAskTaken={() => setAgentAsk(null)}
            onSelect={(s) => (s ? navigate("agent", ...agentParams(s)) : navigate("agent"))} />
        )}
        {active === "stewardship" && <StewardWorkflow initialTab={route.params[0]} />}
        {active === "engagement" && <EngagementDashboard />}
        {active === "reporting" && <ReportBuilder />}
        {active === "valueChain" && <ValueChainExplorer key={route.params.join("/")} params={route.params} />}
        {active === "argusWalkthrough" && <ArgusWalkthrough key={route.params.join("/")} params={route.params} />}
        {active === "rfp" && <RfpAnswers projectId={rfpId(route.params[0])} onOpen={(id) => (id === null ? navigate("rfp") : navigate("rfp", String(id)))} />}
        {active === "library" && <DataLibrary />}
        {active === "companies" && <Company companyRef={route.params[0]} />}
        </Suspense>
        </ErrorBoundary>
      </main>
    </div>
  );
}

/** Opening ARP lands on the landing page; any other address opens the app as before. */
export function AppEntry() {
  const { pathname } = useLocation();
  return entryTab(`#${pathname}`) === "welcome" ? <Landing /> : <App />;
}

function Root() {
  return (
    <HashRouter>
      <AppEntry />
    </HashRouter>
  );
}

export default Root;
