import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { SettingsResponse, CategoryResponse } from "./settingsTypes";

export function useAllSettings() {
  return useQuery<SettingsResponse>({
    queryKey: ["settings"],
    queryFn: () => api<SettingsResponse>("/settings"),
    staleTime: 30_000,
  });
}

export function useCategorySettings(category: string) {
  return useQuery<CategoryResponse>({
    queryKey: ["settings", category],
    queryFn: () => api<CategoryResponse>(`/settings/${encodeURIComponent(category)}`),
    enabled: Boolean(category),
    staleTime: 30_000,
  });
}
