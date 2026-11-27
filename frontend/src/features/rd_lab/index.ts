import { lazy } from "react";

export const ThemeBuilder = lazy(() =>
  import("../../pages/ThemeBuilder").then((x) => ({ default: x.ThemeBuilder })),
);
export const AuthorityTaxonomyRun = lazy(() =>
  import("../../pages/AuthorityTaxonomyRun").then((x) => ({ default: x.AuthorityTaxonomyRun })),
);
export const TaxonomyLibrary = lazy(() =>
  import("../../pages/TaxonomyLibrary").then((x) => ({ default: x.TaxonomyLibrary })),
);
export const EmergingThemesDetector = lazy(() =>
  import("../../pages/EmergingThemesDetector").then((x) => ({ default: x.EmergingThemesDetector })),
);
export const DesignStrategy = lazy(() =>
  import("../../pages/DesignStrategy").then((x) => ({ default: x.DesignStrategy })),
);
export const ThemeDossiers = lazy(() =>
  import("../../pages/ThemeDossiers").then((x) => ({ default: x.ThemeDossiers })),
);
export const ValueChainExplorer = lazy(() =>
  import("../../pages/value-chain/ValueChainExplorer").then((x) => ({ default: x.ValueChainExplorer })),
);
