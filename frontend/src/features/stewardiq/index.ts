import { lazy } from "react";

export const StewardWorkflow = lazy(() =>
  import("../../pages/StewardWorkflow").then((x) => ({ default: x.StewardWorkflow })),
);
export const EngagementDashboard = lazy(() =>
  import("../../pages/EngagementDashboard").then((x) => ({ default: x.EngagementDashboard })),
);
export const PortfolioRiskMonitoringTool = lazy(() =>
  import("../../pages/PortfolioRiskMonitoringTool").then((x) => ({ default: x.PortfolioRiskMonitoringTool })),
);
export const ReportBuilder = lazy(() =>
  import("../../pages/ReportBuilder").then((x) => ({ default: x.ReportBuilder })),
);
export const RfpAnswers = lazy(() =>
  import("../../pages/RfpAnswers").then((x) => ({ default: x.RfpAnswers })),
);
