// The one registry of workspaces and the business processes they run. The
// start page, the workspace pages and the process bar all read it, so a
// process changes in one place. A step links to the screen that does the
// work (often in another workspace: processes cross boxes) and names what it
// hands to the next step; `carried: false` marks a handoff re-entered by hand.
// Live state comes from the run store (`runTypes`) or the house stewardship
// flow (`stage`). See docs/PROCESS_VIEW.md.
import { REVIEWABLE_RUN_TYPES } from "./runs.ts";

export type Step = {
  tab: string;
  sub?: string; // deep-link param, e.g. a Steward Workflow stage
  label: string;
  does: string;
  handsOn?: string;
  carried?: boolean;
  runTypes?: string[];
  /** A Steward Workflow stage whose open decisions this step owns. */
  stage?: string;
  /** Its flagged items wait on a later step (the Review Queue), so its state shows only running/failed/done. */
  reviewedElsewhere?: boolean;
  optional?: boolean;
  /** Not built yet: drawn dimmed and not linked. */
  planned?: boolean;
};
/** `run`: the process has an engine that runs it end to end ("Run process"); the others are walked step by step. */
export type Process = { id: string; title: string; cadence: string; outcome: string; steps: Step[]; run?: "extraction" | "monthly" };
export type WorkspaceId = "stewardiq" | "argus" | "transitionIntel" | "rdLab" | "dataHub";
export type Workspace = {
  id: WorkspaceId;
  name: string;
  /** Fits the sidebar and a start-page card title; `name` stays the page title. */
  short?: string;
  purpose: string;
  /** Runs this workspace produces: its card's waiting/failed/running counts. */
  runTypes: string[];
  processes: Process[];
  /** Every screen of the workspace, for running a single step by hand. */
  screens: [href: string, label: string][];
  /** The screens the workspace row links, in order (default: all of `screens`). The others still belong here. */
  row?: string[];
  /** Screens under the row's "More" menu, in order. */
  more?: string[];
};

const REVIEWABLE = [...REVIEWABLE_RUN_TYPES];
const EXTRACTION_RUNS = ["extraction", "financials", "tnfd", "transition_plan"];

export const WORKSPACES: Workspace[] = [
  {
    id: "stewardiq",
    name: "StewardIQ",
    purpose: "Engage companies, vote, and track what they commit to.",
    runTypes: [],
    screens: [
      ["#/stewardship/workbench", "Workbench"],
      ["#/stewardship/drafting", "Drafting"],
      ["#/engagement", "Engagement"],
      ["#/rfp", "RFP Answers"],
    ],
    processes: [
      {
        id: "engage",
        title: "Engage and draft",
        cadence: "Continuous",
        outcome: "Every issue has an owner, a next step, and reviewed outreach.",
        steps: [
          { tab: "stewardship", sub: "workbench", label: "Workbench", does: "Prioritise companies for engagement, manage programmes, and record notes.", handsOn: "Selection workbench", carried: true },
          { tab: "engagement", label: "Engagement", does: "Issue record: contacts, severity, milestone and escalation stage.", handsOn: "Issue record", carried: true },
          { tab: "stewardship", sub: "drafting", stage: "drafting", label: "Drafting", does: "Dossier, outreach letter and talking points; a person approves before sending.", handsOn: "Sent outreach" },
        ],
      },
      {
        id: "client",
        title: "Stewardship reporting",
        cadence: "Quarterly",
        outcome: "Case studies and annual reporting compiled from engagement records.",
        steps: [
          { tab: "engagement", label: "Engagement", does: "Closed engagements, outcomes, and compiled case studies.", handsOn: "Engagement records", carried: true },
          { tab: "reporting", label: "Presentations & Reports", does: "Assemble and style house decks." },
        ],
      },
    ],
  },
  {
    id: "argus",
    name: "Argus",
    purpose: "Extract cited data points from disclosures and score them.",
    // xbrl_fetch counts for the Argus card but is not in REVIEWABLE: it has nothing to review.
    runTypes: [...EXTRACTION_RUNS, "xbrl_fetch"],
    screens: [
      ["#/argus/new", "New extraction"],
      ["#/argusWalkthrough", "Walkthrough"],
    ],
    // Walkthrough is the Argus page's "How it works" link; Needs you is in the top bar.
    row: ["#/argus/new"],
    processes: [
      {
        id: "extract",
        title: "Extract and score",
        run: "extraction",
        cadence: "Per universe, refreshed when disclosures change",
        outcome: "Every company resolved and documented, every figure cited to a verified source, every flagged one reviewed, and tiers from a ratified template.",
        // The Argus flow's steps: Companies opens a new flow; the others are steps of a flow, so they open the Argus start page.
        steps: [
          { tab: "argus", sub: "new", label: "Companies", does: "Upload, pick a saved universe or add companies one by one, or take one handed over from Data Hub, Risk Monitoring or Thematic Universe; see what is already stored.", handsOn: "Companies", carried: true },
          { tab: "argus", label: "Identify", does: "Resolve each company to one issuer; ambiguous matches wait for review.", handsOn: "Resolved companies", carried: true, runTypes: ["identity"] },
          { tab: "argus", label: "Documents", does: "Discover and download annual, sustainability and proxy reports, or upload your own by type.", handsOn: "Documents", carried: true, runTypes: ["discovery"] },
          { tab: "argus", label: "Schema", optional: true, does: "Custom profile only: the data points to extract and their types.", handsOn: "Schema", carried: true },
          { tab: "argus", label: "Extract", does: "Custom schema, Financials, TNFD or Transition plan profile; every citation re-verified against its source.", handsOn: "Flagged figures", carried: true, runTypes: EXTRACTION_RUNS, reviewedElsewhere: true },
          { tab: "review", label: "Review", does: "Approve, edit or reject every flagged figure.", handsOn: "Reviewed figures", carried: true, runTypes: REVIEWABLE },
        ],
      },
    ],
  },
  {
    id: "transitionIntel",
    name: "Transition Intelligence Platform",
    short: "Transition Intel",
    purpose: "Monitor holdings and assess climate and transition risk.",
    runTypes: ["transition_barrier_refresh"],
    screens: [
      ["#/portfolio-monitoring", "Risk Monitoring"],
      ["#/transitionBarrier", "Transition Barriers"],
      ["#/argus/new/transition_plan", "Transition Plans"],
    ],
    processes: [
      {
        id: "monitor",
        title: "Monthly monitoring",
        run: "monthly",
        cadence: "Monthly, after the holdings and ESG loads",
        outcome: "Every threshold breach and news controversy on a holding is an alert with an owner.",
        steps: [
          { tab: "portfolio-monitoring", sub: "holdings", label: "Holdings Intake", does: "Load the month's holdings and ESG data; the monthly run starts once both are in.", handsOn: "Month's snapshot", carried: true },
          { tab: "portfolio-monitoring", sub: "monitoring", label: "Monitoring & Alerts", does: "Threshold breaches and news controversies on holdings.", handsOn: "Open alerts", carried: true },
          { tab: "stewardship", sub: "workbench", label: "Steward · Workbench", does: "Open alerts raise stewardship triggers; prioritise and open engagements in StewardIQ." },
        ],
      },
      {
        id: "climate",
        title: "Climate transition review",
        cadence: "Annual, plus ad hoc before committees",
        outcome: "A tiered list of issuers to engage, each with a walk-vs-talk verdict and sector context.",
        steps: [
          { tab: "portfolio-monitoring", sub: "monitoring", label: "Risk Monitoring", does: "WACI, financed emissions and data coverage: where the carbon sits.", handsOn: "Holdings in scope", carried: true },
          { tab: "transitionBarrier", label: "Transition Barriers", does: "Sector × jurisdiction barriers: what can a company in this sector realistically commit to?", handsOn: "Sector context", runTypes: ["transition_barrier_refresh"] },
          { tab: "transitionPlan", label: "Transition Plan", does: "64 indicators per issuer, walk vs. talk, each with a grounded citation (run by Argus).", handsOn: "Indicator scores", carried: true, runTypes: ["transition_plan"] },
          { tab: "stewardship", sub: "workbench", label: "Steward · Workbench", does: "Prioritise companies for engagement using transition plan results.", handsOn: "Selection workbench" },
          { tab: "reporting", label: "Presentations & Reports", does: "Committee pack: the assessment with its evidence." },
        ],
      },
    ],
  },
  {
    id: "rdLab",
    name: "R&D Lab",
    purpose: "Research themes and find the companies exposed to them.",
    runTypes: ["emerging_themes", "taxonomy_research", "theme", "calibration"],
    screens: [
      ["#/designStrategy", "Build a thematic portfolio"],
      ["#/themes", "Themes"],
      ["#/emergingThemes", "Emerging Themes"],
      ["#/taxonomy", "Taxonomy Library"],
      ["#/theme", "Thematic Universe"],
      ["#/valueChain", "Value Chain Explorer"],
    ],
    // Emerging Themes is the second tab of Themes (the Themes hub).
    row: ["#/designStrategy", "#/themes"],
    more: ["#/taxonomy", "#/theme", "#/valueChain"],
    processes: [
      {
        id: "thematic",
        title: "Build a thematic portfolio",
        cadence: "Per idea",
        outcome: "A ratified theme, a reviewed universe and published scores.",
        steps: [
          { tab: "emergingThemes", label: "Spot", does: "Candidate themes from filings and news, gated on corporate action.", handsOn: "Promoted theme", carried: true, runTypes: ["emerging_themes"] },
          { tab: "taxonomy", label: "Define", does: "The theme's activities; ratify a version.", handsOn: "Ratified taxonomy", carried: true, runTypes: ["taxonomy_research"] },
          { tab: "theme", label: "Match", does: "Companies matched to activities with exposure estimates and cited rationale.", handsOn: "Theme universe", carried: true, runTypes: ["theme"], reviewedElsewhere: true },
          { tab: "review", label: "Review", does: "Resolve contested classifications.", handsOn: "Reviewed universe", carried: true, runTypes: ["theme"] },
          { tab: "reporting", label: "Report", does: "Committee deck." },
        ],
      },
      {
        id: "theme",
        title: "Research a theme",
        cadence: "Per theme",
        outcome: "One dossier per theme: spotted, defined by a ratified taxonomy, researched, and its exposed companies found and reviewed.",
        steps: [
          { tab: "themes", label: "Spot", does: "An emerging theme with its context: promote an Emerging Themes candidate, or start a dossier from a topic." },
          { tab: "themes", label: "Define", does: "Attach the theme's taxonomy and ratify a version." },
          { tab: "themes", label: "Research", does: "Risks, opportunities and transmission channels from approved authoritative sources." },
          { tab: "themes", label: "Find companies", does: "The exposed universe, measured against the latest ratified taxonomy version and reviewed." },
        ],
      },
    ],
  },
  {
    id: "dataHub",
    name: "Data Hub",
    purpose: "Input feeds, stored data and the security master.",
    runTypes: [],
    screens: [
      ["#/feeds", "Feeds"],
      ["#/issues", "Issues"],
      ["#/smartSearch", "Smart Search"],
      ["#/outputs", "Outputs"],
      ["#/securityMaster", "Security Master"],
      ["#/library", "Data Library"],
      ["#/search", "Search"],
    ],
    // Search and Smart Search are the top bar's search-or-ask box; Holdings Intake is Risk Monitoring's "Load holdings".
    row: ["#/feeds", "#/issues", "#/library", "#/outputs", "#/securityMaster"],
    processes: [
      {
        id: "onboard",
        title: "Map securities to issuers",
        cadence: "When the security master or a holding changes",
        outcome: "Every held security mapped to exactly one internal issuer by the security master, and nothing mapped any other way.",
        steps: [
          { tab: "securityMaster", label: "Load security master", does: "Upload the master: internal issuer id plus ISIN, CUSIP, SEDOL, FIGI, LEI, CIK or PermID. Replaces the golden source whole.", handsOn: "Identifier map", carried: true },
          { tab: "portfolio-monitoring", sub: "holdings", label: "Map holdings", does: "Each holding's ISIN (or LEI) matched exactly to its internal issuer as it loads.", handsOn: "Mapped holdings", carried: true },
          { tab: "securityMaster", label: "Unmatched", does: "Held securities the master does not know: fix the master, not the holding.", handsOn: "Corrections to the master" },
          { tab: "library", label: "Data Library", does: "The issuer view every workspace reads." },
        ],
      },
    ],
  },
];

export const PROCESSES: Process[] = WORKSPACES.flatMap((w) => w.processes);
export const workspaceOfProcess = (id: string | undefined) => WORKSPACES.find((w) => w.processes.some((p) => p.id === id));

// Routes with their own place in the top bar never belong to a workspace.
const OWN_PLACE = new Set(["home", "review", "reporting"]);

/** The workspace a route belongs to, for the workspace row: the longest screens href the hash equals or extends,
 * else the workspace whose overview the tab is, else a process step's screen. */
export function workspaceOfRoute(hash: string): WorkspaceId | null {
  const tab = hash.replace(/^#\/?/, "").split("/")[0];
  if (OWN_PLACE.has(tab)) return null;
  // A listed screen wins over the tab: #/argus/new/transition_plan is Transition Intel's, though its tab is argus.
  let best: [WorkspaceId, number] | null = null;
  for (const w of WORKSPACES)
    for (const [href] of w.screens)
      if ((hash === href || hash.startsWith(href + "/")) && (!best || href.length > best[1])) best = [w.id, href.length];
  if (best) return best[0];
  const own = WORKSPACES.find((w) => w.id === tab);
  if (own) return own.id;
  return WORKSPACES.find((w) => w.processes.some((p) => p.steps.some((s) => s.tab === tab)))?.id ?? null;
}

const pick = (w: Workspace, hrefs: string[]) => hrefs.map((h) => w.screens.find(([href]) => href === h)!);

/** The workspace row's links: the workspace itself, then its row screens. */
export const rowLinks = (w: Workspace): [href: string, label: string][] => [[`#/${w.id}`, w.short ?? w.name], ...(w.row ? pick(w, w.row) : w.screens)];

/** The row's "More" menu, empty when the workspace has none. */
export const moreLinks = (w: Workspace): [href: string, label: string][] => (w.more ? pick(w, w.more) : []);

/** Steward Workflow stages owned by a step; their open decisions are what StewardIQ waits on. */
export const DECISION_STAGES: string[] = [...new Set(PROCESSES.flatMap((p) => p.steps.map((s) => s.stage).filter((s): s is string => !!s)))];

export const stepHref = (step: Step) => `#/${[step.tab, step.sub].filter(Boolean).map((p) => encodeURIComponent(p!)).join("/")}`;
