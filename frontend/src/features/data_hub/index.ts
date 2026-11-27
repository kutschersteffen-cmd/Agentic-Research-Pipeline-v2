import { lazy } from "react";

export const Search = lazy(() =>
  import("../../pages/Search").then((x) => ({ default: x.Search })),
);
export const SecurityMaster = lazy(() =>
  import("../../pages/SecurityMaster").then((x) => ({ default: x.SecurityMaster })),
);
export const Feeds = lazy(() =>
  import("../../pages/Feeds").then((x) => ({ default: x.Feeds })),
);
export const Issues = lazy(() =>
  import("../../pages/Issues").then((x) => ({ default: x.Issues })),
);
export const SmartSearch = lazy(() =>
  import("../../pages/SmartSearch").then((x) => ({ default: x.SmartSearch })),
);
export const Outputs = lazy(() =>
  import("../../pages/Outputs").then((x) => ({ default: x.Outputs })),
);
export const DataLibrary = lazy(() =>
  import("../../pages/DataLibrary").then((x) => ({ default: x.DataLibrary })),
);
export const Company = lazy(() =>
  import("../../pages/Company").then((x) => ({ default: x.Company })),
);
