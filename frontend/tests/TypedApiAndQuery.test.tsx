import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { createTypedClient, unwrap } from "../src/api/typedClient";
import { clearToken, getToken, setToken } from "../src/lib/auth";
import { createQueryClient } from "../src/lib/queryClient";
import { AppEntry } from "../src/App";

function requestUrl(input: RequestInfo | URL): string {
  return typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
}

beforeEach(() => {
  clearToken();
  vi.stubGlobal("scrollTo", vi.fn());
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  );
});

afterEach(() => {
  clearToken();
  cleanup();
  vi.unstubAllGlobals();
});

describe("typed openapi-fetch client", () => {
  it("attaches bearer token, unwraps data, and clears token on 401", async () => {
    setToken("secret-token");
    let seenAuth: string | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
        if (input instanceof Request) seenAuth = input.headers.get("Authorization");
        return new Response(JSON.stringify({ id: "u1", name: "Ana", role: "analyst" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    const client = createTypedClient("http://localhost:8000");
    const data = unwrap(await client.GET("/api/me"));
    expect(seenAuth).toBe("Bearer secret-token");
    expect(data).toMatchObject({ name: "Ana" });

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "expired" }), {
          status: 401,
          statusText: "Unauthorized",
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    await expect(client.GET("/api/me").then(unwrap)).rejects.toThrow("401: expired");
    expect(getToken()).toBe("");
  });

  it("formats array, object, string, and fallback error responses cleanly", () => {
    const mk = (status: number, statusText = "Bad Request") => new Response("", { status, statusText });
    expect(() => unwrap({ error: { detail: [{ loc: ["body", "name"], msg: "required" }] }, response: mk(422) })).toThrow(
      /422:.*name/,
    );
    expect(() => unwrap({ error: { detail: { code: "bad" } }, response: mk(400) })).toThrow('400: {"code":"bad"}');
    expect(() => unwrap({ error: "raw failure", response: mk(500) })).toThrow("500: raw failure");
    expect(() => unwrap({ error: { other: 1 }, response: mk(500) })).toThrow('500: {"other":1}');
    expect(() => unwrap({ error: undefined, response: mk(503, "Service Unavailable") })).toThrow(
      "503: Service Unavailable",
    );
  });

  it("falls back to statusText for empty-body non-2xx responses and resolves relative baseUrls", async () => {
    const seenUrls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
        seenUrls.push(requestUrl(input));
        return new Response("", { status: 503, statusText: "Service Unavailable" });
      }),
    );

    const sameOrigin = createTypedClient("");
    await expect(sameOrigin.GET("/api/me").then(unwrap)).rejects.toThrow("503: Service Unavailable");
    const relativePrefix = createTypedClient(".");
    await expect(relativePrefix.GET("/api/me").then(unwrap)).rejects.toThrow("503: Service Unavailable");
    expect(seenUrls.every((u) => u.endsWith("/api/me"))).toBe(true);
  });
});

describe("TanStack Query integration in App", () => {
  it("refetches waiting counts when arp:decided fires and hides badge on error", async () => {
    let waitingCalls = 0;
    let failWaiting = false;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
        const url = requestUrl(input);
        if (url.includes("/api/waiting")) {
          waitingCalls += 1;
          if (failWaiting) return new Response(JSON.stringify({ detail: "down" }), { status: 500, headers: { "Content-Type": "application/json" } });
          return new Response(JSON.stringify({ review: 3, decisions: 0, ballots: 0, total: 3 }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.includes("/api/me")) {
          return new Response(JSON.stringify({ id: "u1", name: "Ana", role: "analyst" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.includes("/api/stewardship/drafts")) {
          return new Response(JSON.stringify({ drafts: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
        }
        if (url.includes("/api/runs")) {
          return new Response(JSON.stringify({ runs: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
        }
        return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );

    const client = createQueryClient();
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/home"]}>
          <AppEntry />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => expect(document.querySelector(".nav-count")?.textContent).toBe("3"));
    const before = waitingCalls;
    failWaiting = true;
    window.dispatchEvent(new Event("arp:decided"));
    await waitFor(() => expect(waitingCalls).toBeGreaterThan(before));
    await waitFor(() => expect(document.querySelector(".nav-count")).toBeNull());
  });
});
