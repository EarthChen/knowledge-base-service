import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "../AuthContext";

function AuthProbe() {
  const auth = useAuth();
  return (
    <div
      data-testid="auth-probe"
      data-auth-resolved={String(auth.authResolved)}
      data-auth-enabled={String(auth.authEnabled)}
      data-is-admin={String(auth.isAdmin)}
      data-is-editor={String(auth.isEditor)}
      data-auth-error={String(auth.authError)}
      data-is-loading={String(auth.isLoading)}
    />
  );
}

function renderAuth(queryData?: object) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  if (queryData !== undefined) {
    client.setQueryData(["auth-me"], queryData);
  }
  const { container } = render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>
    </QueryClientProvider>,
  );
  return container.querySelector("[data-testid='auth-probe']")!;
}

describe("AuthContext deny-by-default", () => {
  it("denies admin/editor while auth is loading", () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    const { container } = render(
      <QueryClientProvider client={client}>
        <AuthProvider>
          <AuthProbe />
        </AuthProvider>
      </QueryClientProvider>,
    );
    const el = container.querySelector("[data-testid='auth-probe']")!;
    expect(el.getAttribute("data-auth-resolved")).toBe("false");
    expect(el.getAttribute("data-is-admin")).toBe("false");
    expect(el.getAttribute("data-is-editor")).toBe("false");
    expect(el.getAttribute("data-is-loading")).toBe("true");
  });

  it("grants full access when auth is deliberately disabled", () => {
    const el = renderAuth({ role: null, auth_enabled: false, business_id: null });
    expect(el.getAttribute("data-auth-resolved")).toBe("true");
    expect(el.getAttribute("data-auth-enabled")).toBe("false");
    expect(el.getAttribute("data-is-admin")).toBe("true");
    expect(el.getAttribute("data-is-editor")).toBe("true");
  });

  it("grants admin only for admin role when auth is enabled", () => {
    const el = renderAuth({ role: "admin", auth_enabled: true, business_id: null });
    expect(el.getAttribute("data-is-admin")).toBe("true");
    expect(el.getAttribute("data-is-editor")).toBe("true");
  });

  it("grants editor but not admin for editor role when auth is enabled", () => {
    const el = renderAuth({ role: "editor", auth_enabled: true, business_id: null });
    expect(el.getAttribute("data-is-admin")).toBe("false");
    expect(el.getAttribute("data-is-editor")).toBe("true");
  });

  it("denies admin/editor for viewer when auth is enabled", () => {
    const el = renderAuth({ role: "viewer", auth_enabled: true, business_id: null });
    expect(el.getAttribute("data-is-admin")).toBe("false");
    expect(el.getAttribute("data-is-editor")).toBe("false");
  });

  it("sets authError when /auth/me fetch fails", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    client.setQueryDefaults(["auth-me"], {
      queryFn: () => Promise.reject(new Error("network")),
    });
    const { container } = render(
      <QueryClientProvider client={client}>
        <AuthProvider>
          <AuthProbe />
        </AuthProvider>
      </QueryClientProvider>,
    );
    await vi.waitFor(() => {
      const el = container.querySelector("[data-testid='auth-probe']")!;
      expect(el.getAttribute("data-auth-error")).toBe("true");
    });
  });
});
