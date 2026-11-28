import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useNavigate } from "react-router-dom";
import Root, { AppEntry } from "../src/App";
import { ErrorBoundary } from "../src/components/ErrorBoundary";
import { setLeaveGuard } from "../src/lib/leaveGuard";
import { createQueryClient } from "../src/lib/queryClient";

function requestUrl(input: RequestInfo | URL): string {
  return typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
}

function renderEntry(initialEntries: string[], extra?: React.ReactNode) {
  const client = createQueryClient();
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={initialEntries}>
        <AppEntry />
        {extra}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// Stub WebGL / canvas / dialog / matchMedia / scrollTo for jsdom.
beforeEach(() => {
  if (!HTMLDialogElement.prototype.showModal) {
    HTMLDialogElement.prototype.showModal = function () {
      this.setAttribute("open", "");
    };
  }
  if (!HTMLDialogElement.prototype.close) {
    HTMLDialogElement.prototype.close = function () {
      this.removeAttribute("open");
    };
  }
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
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.includes("/api/me")) {
        return new Response(JSON.stringify({ id: "u1", name: "Analyst", role: "analyst" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/api/waiting")) {
        return new Response(JSON.stringify({ total: 0, by_type: {} }), {
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
      if (url.includes("/api/agent/plans") || url.includes("/api/agent/ask") || url.includes("/api/agent/explorations") || url.includes("/api/agent/refine")) {
        return new Response(JSON.stringify({ plans: [], threads: [], explorations: [], items: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
});

afterEach(() => {
  setLeaveGuard(null);
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = "";
});

function NavButton({ to, label }: { to: string; label: string }) {
  const nav = useNavigate();
  return <button onClick={() => nav(to)}>{label}</button>;
}

describe("App routing with HashRouter / MemoryRouter", () => {
  it("renders Landing on / and /welcome", () => {
    const { unmount } = renderEntry(["/"]);
    expect(document.querySelector(".app-shell-start")).toBeNull();
    unmount();

    renderEntry(["/welcome"]);
    expect(document.querySelector(".app-shell-start")).toBeNull();
  });

  it("renders the app shell and Start page on /home and unknown routes", async () => {
    renderEntry(["/home"]);
    expect(screen.getByText("Skip to content")).toBeTruthy();
    await waitFor(() => expect(document.title).toContain("Start"));
    cleanup();

    renderEntry(["/does-not-exist"]);
    await waitFor(() => expect(document.title).toContain("Start"));
  });

  it("redirects retired routes and legacy aliases to their target screens", async () => {
    renderEntry(["/extraction"]);
    await waitFor(() => expect(document.title).toContain("Argus"));
    cleanup();

    renderEntry(["/themeMachine"]);
    await waitFor(() => expect(document.title).toContain("R&D Lab"));
    cleanup();

    renderEntry(["/processes/extract"]);
    await waitFor(() => expect(document.title).toContain("Argus"));
  });

  it("blocks navigation when canLeave() returns false without scrolling to top", async () => {
    const guard = vi.fn(() => false);
    setLeaveGuard(guard);
    renderEntry(["/home"], <NavButton to="/rdLab" label="Go RD" />);
    await waitFor(() => expect(document.title).toContain("Start"));
    fireEvent.click(screen.getByText("Go RD"));
    await waitFor(() => expect(guard).toHaveBeenCalledTimes(1));
    expect(document.title).toContain("Start");
    expect(window.scrollTo).not.toHaveBeenCalled();
  });

  it("opens command palette on Ctrl+K and navigates to Agent on Ctrl+J when allowed", async () => {
    renderEntry(["/home"]);
    await waitFor(() => expect(document.title).toContain("Start"));
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.getByRole("dialog")).toBeTruthy();

    fireEvent.keyDown(window, { key: "j", ctrlKey: true });
    await waitFor(() => expect(document.title).toContain("Runs"));
  });

  it("mounts default Root with HashRouter cleanly", async () => {
    window.location.hash = "#/home";
    render(<Root />);
    await waitFor(() => expect(document.title).toContain("Start"));
  });

  it("clears ErrorBoundary error when resetKey changes", () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    function Boom({ fail }: { fail: boolean }) {
      if (fail) throw new Error("boom");
      return <div>recovered</div>;
    }
    const { rerender } = render(
      <ErrorBoundary resetKey="a">
        <Boom fail={true} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("This screen stopped working")).toBeTruthy();
    rerender(
      <ErrorBoundary resetKey="b">
        <Boom fail={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("recovered")).toBeTruthy();
    errSpy.mockRestore();
  });
});
