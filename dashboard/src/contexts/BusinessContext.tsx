import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuth } from "./AuthContext";
import type { Business, BusinessesResponse } from "../api/types";

const STORAGE_KEY = "kb_business_id";

function getStoredBusiness(): string {
  return localStorage.getItem(STORAGE_KEY) || "default";
}

interface BusinessContextType {
  currentBusiness: string;
  setCurrentBusiness: (id: string) => void;
  businesses: Business[];
  isLoading: boolean;
  isBound: boolean;
}

const BusinessContext = createContext<BusinessContextType>({
  currentBusiness: "default",
  setCurrentBusiness: () => {},
  businesses: [],
  isLoading: false,
  isBound: false,
});

export function BusinessProvider({ children }: { children: React.ReactNode }) {
  const { boundBusiness } = useAuth();
  const isBound = boundBusiness !== null;

  const [currentBusiness, setCurrentBusinessState] = useState(() =>
    boundBusiness ?? getStoredBusiness()
  );
  const queryClient = useQueryClient();

  useEffect(() => {
    if (boundBusiness !== null && currentBusiness !== boundBusiness) {
      setCurrentBusinessState(boundBusiness);
      localStorage.setItem(STORAGE_KEY, boundBusiness);
      queryClient.invalidateQueries();
    }
  }, [boundBusiness, currentBusiness, queryClient]);

  const { data, isLoading } = useQuery<BusinessesResponse>({
    queryKey: ["businesses"],
    queryFn: () => api("/businesses", { method: "GET" }),
    staleTime: 60_000,
  });

  const setCurrentBusiness = useCallback(
    (id: string) => {
      if (isBound) return;
      localStorage.setItem(STORAGE_KEY, id);
      setCurrentBusinessState(id);
      queryClient.invalidateQueries();
    },
    [queryClient, isBound],
  );

  useEffect(() => {
    if (
      !isBound &&
      data?.businesses?.length &&
      !data.businesses.some((b) => b.id === currentBusiness)
    ) {
      setCurrentBusiness("default");
    }
  }, [data, currentBusiness, setCurrentBusiness, isBound]);

  return (
    <BusinessContext.Provider
      value={{
        currentBusiness,
        setCurrentBusiness,
        businesses: data?.businesses ?? [],
        isLoading,
        isBound,
      }}
    >
      {children}
    </BusinessContext.Provider>
  );
}

export function useBusiness() {
  return useContext(BusinessContext);
}

export function getCurrentBusiness(): string {
  return getStoredBusiness();
}
