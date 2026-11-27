import { lazy } from "react";

export const Agent = lazy(() =>
  import("../../pages/Agent").then((x) => ({ default: x.Agent })),
);
export const BackgroundAgents = lazy(() =>
  import("../../pages/BackgroundAgents").then((x) => ({ default: x.BackgroundAgents })),
);
export const ReviewQueue = lazy(() =>
  import("../../pages/ReviewQueue").then((x) => ({ default: x.ReviewQueue })),
);
export const RunHistory = lazy(() =>
  import("../../pages/RunHistory").then((x) => ({ default: x.RunHistory })),
);
