import { lazy } from "react";

export const TransitionBarrierAssessment = lazy(() => import("../../pages/TransitionBarrierAssessment").then((x) => ({ default: x.TransitionBarrierAssessment })));
