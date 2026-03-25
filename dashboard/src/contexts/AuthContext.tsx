import { createContext, useContext } from "react";
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
  isLoading: boolean;
  isAdmin: boolean;
  isEditor: boolean;
  isViewer: boolean;
  boundBusiness: string | null;
}

const AuthContext = createContext<AuthContextType>({
  role: null,
  authEnabled: false,
  isLoading: true,
  isAdmin: false,
  isEditor: false,
  isViewer: false,
  boundBusiness: null,
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { data, isLoading } = useQuery<AuthInfo>({
    queryKey: ["auth-me"],
    queryFn: () => api("/auth/me", { method: "GET" }),
    staleTime: 120_000,
    retry: false,
  });

  const role = data?.role ?? null;
  const authEnabled = data?.auth_enabled ?? false;
  const boundBusiness = data?.business_id ?? null;

  const isAdmin = !authEnabled || role === "admin";
  const isEditor = isAdmin || role === "editor";
  const isViewer = isEditor || role === "viewer";

  return (
    <AuthContext.Provider
      value={{ role, authEnabled, isLoading, isAdmin, isEditor, isViewer, boundBusiness }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
