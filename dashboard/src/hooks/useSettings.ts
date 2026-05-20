import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { SettingsResponse, CategoryResponse } from "./settingsTypes";

export function useAllSettings() {
  return useQuery<SettingsResponse>({
    queryKey: queryKeys.settings,
    queryFn: () => api<SettingsResponse>("/settings"),
  });
}

export function useCategorySettings(category: string) {
  return useQuery<CategoryResponse>({
    queryKey: queryKeys.settingsCategory(category),
    queryFn: () => api<CategoryResponse>(`/settings/${encodeURIComponent(category)}`),
    enabled: Boolean(category),
  });
}
