import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { SettingsBatchUpdate, TestConnectionResponse } from "./settingsTypes";

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation<{ status: string; updated: string }, ApiError, SettingsBatchUpdate>({
    mutationFn: (body) =>
      api<{ status: string; updated: string }>("/settings", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.settings });
    },
  });
}

export function useDeleteSetting() {
  const qc = useQueryClient();
  return useMutation<{ status: string; key: string }, ApiError, string>({
    mutationFn: (key) =>
      api<{ status: string; key: string }>(`/settings/${encodeURIComponent(key)}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.settings });
    },
  });
}

export function useTestConnection() {
  return useMutation<TestConnectionResponse, ApiError, string>({
    mutationFn: (target) =>
      api<TestConnectionResponse>("/settings/test-connection", {
        method: "POST",
        body: JSON.stringify({ target }),
      }),
  });
}
