import { describe, it, expect } from "vitest";
import { useState } from "react";
import { render, fireEvent, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "../AuthContext";
import { BusinessProvider, useBusiness } from "../BusinessContext";

describe("context value referential stability", () => {
  it("AuthContext value is stable across parent re-renders when query data is unchanged", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    client.setQueryData(["auth-me"], {
      role: "admin",
      auth_enabled: true,
      business_id: null,
    });

    const refs: unknown[] = [];

    function Probe() {
      refs.push(useAuth());
      return null;
    }

    function Shell() {
      const [n, setN] = useState(0);
      return (
        <>
          <button type="button" data-testid="bump" onClick={() => setN((x) => x + 1)}>
            {n}
          </button>
          <AuthProvider>
            <Probe />
          </AuthProvider>
        </>
      );
    }

    render(
      <QueryClientProvider client={client}>
        <Shell />
      </QueryClientProvider>,
    );

    const first = refs[refs.length - 1];
    expect(refs.length).toBeGreaterThanOrEqual(1);

    fireEvent.click(screen.getByTestId("bump"));

    const last = refs[refs.length - 1];
    expect(last).toBe(first);
  });

  it("BusinessContext value is stable across parent re-renders when query data is unchanged", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    client.setQueryData(["auth-me"], {
      role: "admin",
      auth_enabled: false,
      business_id: null,
    });
    client.setQueryData(["businesses"], {
      businesses: [
        { id: "default", name: "Default", description: "", created_at: 0 },
      ],
      total: 1,
    });

    const refs: unknown[] = [];

    function Probe() {
      refs.push(useBusiness());
      return null;
    }

    function Shell() {
      const [n, setN] = useState(0);
      return (
        <>
          <button type="button" data-testid="bump-biz" onClick={() => setN((x) => x + 1)}>
            {n}
          </button>
          <AuthProvider>
            <BusinessProvider>
              <Probe />
            </BusinessProvider>
          </AuthProvider>
        </>
      );
    }

    render(
      <QueryClientProvider client={client}>
        <Shell />
      </QueryClientProvider>,
    );

    const idxAfterMount = refs.length;
    const first = refs[idxAfterMount - 1];

    fireEvent.click(screen.getByTestId("bump-biz"));

    const last = refs[refs.length - 1];
    expect(last).toBe(first);
  });
});
