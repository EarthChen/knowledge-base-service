import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { SettingsBatchUpdate, TestConnectionResponse } from "./settingsTypes";

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SettingsBatchUpdate) =>
      api<{ status: string; updated: string }>("/settings", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
  });
}

export function useDeleteSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (key: string) =>
      api<{ status: string; key: string }>(`/settings/${encodeURIComponent(key)}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
  });
}

export function useTestConnection() {
  return useMutation({
    mutationFn: (target: string) =>
      api<TestConnectionResponse>("/settings/test-connection", {
        method: "POST",
        body: JSON.stringify({ target }),
      }),
  });
}
