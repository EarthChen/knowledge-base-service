import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useI18n } from "../../i18n/context";

type ApiRow = {
  uid: string;
  claim_text: string;
  version: number;
  superseded_by?: string | null;
  created_at?: number;
  superseded_at?: number | null;
};

export function ClaimHistoryPanel({ pageUid }: { pageUid: string }) {
  const { t } = useI18n();
  const claimI18n = t.wiki.claims;
  const q = useQuery({
    queryKey: ["wiki", "claim-history", pageUid],
    queryFn: () =>
      api<{ items: ApiRow[] }>(
        `/wiki/pages/claim-history?page_uid=${encodeURIComponent(pageUid)}`,
      ),
    enabled: Boolean(pageUid.trim()),
  });
  const claims = q.data?.items ?? [];
  if (!pageUid.trim()) return null;
  if (q.isLoading) {
    return (
      <p className="mt-6 text-xs text-gray-500 dark:text-gray-400" role="status">
        {claimI18n.loading}
      </p>
    );
  }
  if (q.isError) {
    return (
      <p className="mt-6 text-xs text-red-600 dark:text-red-400" role="alert">
        {claimI18n.load_failed}
      </p>
    );
  }
  if (!claims.length) return null;
  return (
    <details className="mt-6 rounded-lg border border-gray-200 p-3 dark:border-gray-700">
      <summary className="cursor-pointer text-sm font-semibold text-gray-800 dark:text-gray-200">
        {claimI18n.history}
      </summary>
      <ol className="mt-2 space-y-2 text-sm text-gray-700 dark:text-gray-300">
        {claims.map((row) => (
          <li key={row.uid}>
            <span className="font-mono text-xs text-gray-500 dark:text-gray-500">v{row.version}</span>{" "}
            {row.claim_text}
            {row.superseded_by ? (
              <span className="ml-2 text-xs text-amber-700 dark:text-amber-400">{claimI18n.superseded}</span>
            ) : null}
          </li>
        ))}
      </ol>
    </details>
  );
}
