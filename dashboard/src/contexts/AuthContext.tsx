import { createContext, useContext, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

interface AuthInfo {
  role: string | null;
  auth_enabled: boolean;
  business_id: string | null;
}

interface AuthContextType {
  role: string | null;
  authEnabled: boolean;
  authResolved: boolean;
  authError: boolean;
  isLoading: boolean;
  isAdmin: boolean;
  isEditor: boolean;
  isViewer: boolean;
  boundBusiness: string | null;
}

const AuthContext = createContext<AuthContextType>({
  role: null,
  authEnabled: false,
  authResolved: false,
  authError: false,
  isLoading: true,
  isAdmin: false,
  isEditor: false,
  isViewer: false,
  boundBusiness: null,
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { data, isLoading, isError } = useQuery<AuthInfo>({
    queryKey: ["auth-me"],
    queryFn: () => api("/auth/me", { method: "GET" }),
    staleTime: 120_000,
    retry: false,
  });

  const authResolved = !isLoading;
  const authError = isError;
  const role = data?.role ?? null;
  const authEnabled = data?.auth_enabled === true;
  const boundBusiness = data?.business_id ?? null;

  const authDisabled = authResolved && data?.auth_enabled === false;

  let isAdmin: boolean;
  let isEditor: boolean;
  let isViewer: boolean;

  if (authDisabled) {
    isAdmin = true;
    isEditor = true;
    isViewer = true;
  } else if (!authResolved || !authEnabled) {
    isAdmin = false;
    isEditor = false;
    isViewer = false;
  } else {
    isAdmin = role === "admin";
    isEditor = role === "admin" || role === "editor";
    isViewer = isEditor || role === "viewer";
  }

  const value = useMemo(
    () => ({
      role,
      authEnabled,
      authResolved,
      authError,
      isLoading,
      isAdmin,
      isEditor,
      isViewer,
      boundBusiness,
    }),
    [role, authEnabled, authResolved, authError, isLoading, isAdmin, isEditor, isViewer, boundBusiness],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
