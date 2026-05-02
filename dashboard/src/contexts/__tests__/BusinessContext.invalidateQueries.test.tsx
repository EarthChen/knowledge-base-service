import { describe, it, expect, vi } from "vitest";
import { useEffect } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { Query } from "@tanstack/react-query";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../AuthContext";
import { BusinessProvider, useBusiness } from "../BusinessContext";

describe("BusinessContext invalidateQueries", () => {
  it("calls invalidateQueries with a predicate that skips the businesses query", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    client.setQueryData(["auth-me"], {
      role: "admin",
      auth_enabled: false,
      business_id: null,
    });
    client.setQueryData(["businesses"], {
      businesses: [{ id: "default", name: "Default", description: "", created_at: 0 }],
      total: 1,
    });

    const spy = vi.spyOn(client, "invalidateQueries");

    function SwitchBiz() {
      const { setCurrentBusiness } = useBusiness();
      return (
        <button type="button" onClick={() => setCurrentBusiness("other")}>
          switch
        </button>
      );
    }

    render(
      <QueryClientProvider client={client}>
        <AuthProvider>
          <BusinessProvider>
            <SwitchBiz />
          </BusinessProvider>
        </AuthProvider>
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "switch" }));

    expect(spy).toHaveBeenCalled();
    const opts = spy.mock.calls[0]?.[0];
    expect(opts).toMatchObject({
      predicate: expect.any(Function),
    });
    const predicate = (opts as { predicate: (q: Query) => boolean }).predicate;
    expect(predicate({ queryKey: ["businesses"] } as Query)).toBe(false);
    expect(predicate({ queryKey: ["wiki", "x"] } as Query)).toBe(true);
  });

  it("uses predicate when syncing bound business from auth", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    client.setQueryData(["auth-me"], {
      role: "viewer",
      auth_enabled: true,
      business_id: null,
    });
    client.setQueryData(["businesses"], {
      businesses: [
        { id: "default", name: "Default", description: "", created_at: 0 },
        { id: "forced", name: "Forced", description: "", created_at: 0 },
      ],
      total: 2,
    });

    const spy = vi.spyOn(client, "invalidateQueries");

    function BumpAuth() {
      const qc = client;
      useEffect(() => {
        qc.setQueryData(["auth-me"], {
          role: "viewer",
          auth_enabled: true,
          business_id: "forced",
        });
      }, [qc]);
      return null;
    }

    render(
      <QueryClientProvider client={client}>
        <AuthProvider>
          <BusinessProvider>
            <BumpAuth />
          </BusinessProvider>
        </AuthProvider>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(spy).toHaveBeenCalled();
    });
    const opts = spy.mock.calls.find((c) => c[0] && typeof c[0] === "object" && "predicate" in c[0])?.[0];
    expect(opts).toMatchObject({
      predicate: expect.any(Function),
    });
    const predicate = (opts as { predicate: (q: Query) => boolean }).predicate;
    expect(predicate({ queryKey: ["businesses"] } as Query)).toBe(false);
    expect(predicate({ queryKey: ["health"] } as Query)).toBe(true);
  });
});
