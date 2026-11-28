import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api } from "../src/api/client";
import { ActivityEditorTable } from "../src/components/ActivityEditorTable";
import { PortfolioView } from "../src/pages/value-chain/PortfolioView";
import type { ActivityDefinition } from "../src/types";

function requestUrl(input: RequestInfo | URL): string {
  return typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("EXIOBASE sectors UI and client", () => {
  it("fetches EXIOBASE sectors from /api/value-chain/codes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify([{ name: "Copper production" }, { name: "Aluminium production" }]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const sectors = await api.valueChainCodes();
    expect(sectors).toEqual([{ name: "Copper production" }, { name: "Aluminium production" }]);
  });

  it("renders unmapped_sectors warning and hides empty standards mapping in ActivityEditorTable", () => {
    const activities: ActivityDefinition[] = [
      {
        activity_id: "a1",
        name: "Copper smelting",
        in_scope_description: "Primary copper",
        out_of_scope_description: "Retail",
        seed_keywords: ["copper"],
        core_sectors: ["Copper production"],
        standards_mapping: {
          activity_id: "a1",
          activity_name: "Copper smelting",
          nace_codes: [],
          naics_codes: [],
          sic_codes: [],
          gics: [],
          unmapped_sectors: ["Copper production", "Mining of copper ores and concentrates"],
        },
      },
      {
        activity_id: "a2",
        name: "Empty mapping",
        in_scope_description: "In",
        out_of_scope_description: "Out",
        seed_keywords: ["x"],
        core_sectors: [],
        standards_mapping: {
          activity_id: "a2",
          activity_name: "Empty mapping",
          nace_codes: [],
          naics_codes: [],
          sic_codes: [],
          gics: [],
          unmapped_sectors: [],
        },
      },
    ];
    render(<ActivityEditorTable activities={activities} onChange={() => {}} />);
    expect(screen.getByText("No crosswalk entry for Copper production, Mining of copper ores and concentrates")).toBeTruthy();
  });

  it("loads, edits, and saves multi-sector split rules in PortfolioView", async () => {
    const savedBodies: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = requestUrl(input);
        const method = init?.method ?? "GET";
        if (url.endsWith("/api/portfolio/portfolios")) {
          return new Response(JSON.stringify([{ portfolio_id: "p1", name: "Fund 1" }]), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.endsWith("/api/taxonomies")) {
          return new Response(
            JSON.stringify({
              taxonomies: [
                {
                  taxonomy_id: "t1",
                  name: "Grid",
                  version: 1,
                  theme: {
                    theme_id: "th1",
                    name: "Grid",
                    description: "",
                    created_at: "2026-01-01T00:00:00Z",
                    activities: [
                      {
                        activity_id: "a1",
                        name: "Copper mining",
                        in_scope_description: "",
                        out_of_scope_description: "",
                        seed_keywords: [],
                        core_sectors: ["Mining of copper ores and concentrates"],
                      },
                    ],
                  },
                },
              ],
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.endsWith("/api/value-chain/codes")) {
          return new Response(
            JSON.stringify([
              { name: "Copper production" },
              { name: "Mining of copper ores and concentrates" },
            ]),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.includes("/api/value-chain/portfolio/p1")) {
          return new Response(
            JSON.stringify({
              as_of: "2026-09-30",
              nav_eur: 1000,
              linked_weight: 1,
              attributed_weight: 1,
              holdings: [
                {
                  security_id: "s1",
                  company_id: "c1",
                  name: "Acme Copper",
                  market_value_eur: 1000,
                  weight: 1,
                  link_source: "split",
                  top_node: { node_id: "DE.1", region_label: "DE", sector: "Copper production", weight: 1 },
                  owned_output_meur: 1,
                },
              ],
              nodes: [],
              direct_by_region: [],
              upstream_total: 0,
              upstream_by_region: [],
              upstream_by_sector: [],
              upstream_nodes: [],
              footprint: { indicator: "ghg", unit: "t CO₂e", total: 10, per_meur_invested: 10, by_region: [] },
              activity: {
                taxonomy_id: "t1",
                activity_id: "a1",
                name: "Copper mining",
                direct_weight: 0.5,
                upstream_share: 0.2,
              },
              caveat: "EXIOBASE caveat",
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.includes("/api/value-chain/links/company/c1") && method === "GET") {
          return new Response(
            JSON.stringify({
              subject: "company:c1",
              source: "split",
              region: "DE",
              nodes: [],
              unresolved: [],
              rule: {
                kind: "split",
                parts: [{ sectors: ["Copper production"], share: 1 }],
                set_by: "analyst",
                set_at: "2026-01-01T00:00:00Z",
              },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.includes("/api/value-chain/links/company/c1") && method === "PUT") {
          savedBodies.push(JSON.parse(String(init?.body ?? "{}")));
          return new Response(
            JSON.stringify({
              subject: "company:c1",
              source: "split",
              region: "DE",
              nodes: [],
              unresolved: [],
              rule: {
                kind: "split",
                parts: [{ sectors: ["Copper production", "Mining of copper ores and concentrates"], share: 1 }],
                set_by: "analyst",
                set_at: "2026-01-01T00:00:00Z",
              },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.includes("/api/value-chain/links/activity/t1/a1")) {
          return new Response(
            JSON.stringify({
              subject: "activity:t1/a1",
              source: "code",
              region: null,
              nodes: [],
              unresolved: [],
              rule: null,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        return new Response(JSON.stringify({}), { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );

    render(<PortfolioView id="p1" />);
    const editButtons = await screen.findAllByRole("button", { name: "Edit link" });
    // Company link editor: opens with stored split rule and multi-select Sectors
    fireEvent.click(editButtons[0]);
    const select = (await screen.findByLabelText(/Sectors/)) as HTMLSelectElement;
    expect(select.multiple).toBe(true);
    for (const opt of Array.from(select.options)) {
      opt.selected = true;
    }
    fireEvent.change(select);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(savedBodies.length).toBe(1));
    expect(savedBodies[0]).toEqual({
      kind: "split",
      parts: [{ sectors: ["Copper production", "Mining of copper ores and concentrates"], share: 1 }],
    });

    // Activity link editor: default help text refers to EXIOBASE sectors
    fireEvent.click(editButtons[1]);
    expect(await screen.findByText("Uses the activity's core EXIOBASE sectors, in every region.")).toBeTruthy();
  });
});
