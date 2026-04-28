import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useI18n } from "../i18n/context";

export function useWikiIncremental(repository: string) {
  const queryClient = useQueryClient();
  const { locale } = useI18n();
  const lang = locale === "zh" ? "zh" : "en";

  return useMutation({
    mutationFn: async () => {
      return api<{ task_id?: string } & Record<string, unknown>>("/wiki/generate-incremental", {
        method: "POST",
        body: JSON.stringify({ repository: repository.trim(), language: lang }),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["wiki"] });
    },
  });
}
