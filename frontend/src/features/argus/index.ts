import { lazy } from "react";

export { ArgusFlow } from "../../pages/ArgusFlow";
export { ArgusNew, ArgusStart, openNewFlow } from "../../pages/ArgusStart";
export const ArgusWalkthrough = lazy(() =>
  import("../../pages/ArgusWalkthrough").then((x) => ({ default: x.ArgusWalkthrough })),
);
