import { Loader2 } from "lucide-react";
import type { WikiVersion } from "../../hooks/wikiTypes";
import { useWikiVersions } from "../../hooks/useWikiVersions";

interface WikiVersionHistoryProps {
  pageUid: string;
  onSelectVersions: (from: number, to: number) => void;
}

export default function WikiVersionHistory({ pageUid, onSelectVersions }: WikiVersionHistoryProps) {
  const { data: versions, isLoading } = useWikiVersions(pageUid);

  if (isLoading) {
    return (
      <div className="flex justify-center py-4">
        <Loader2 className="size-5 animate-spin text-gray-400" />
      </div>
    );
  }

  if (!versions?.length) {
    return <p className="py-4 text-center text-xs text-gray-500">No version history available</p>;
  }

  return (
    <div className="space-y-2 py-2">
      {versions.map((v: WikiVersion, i: number) => {
        const prev = versions[i + 1];
        return (
          <div
            key={v.version}
            className="flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-800"
          >
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-sky-50 text-xs font-bold text-sky-700 dark:bg-sky-950 dark:text-sky-300">
              v{v.version}
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm text-gray-900 dark:text-gray-100">
                {v.change_summary || "Updated"}
              </p>
              <p className="text-[11px] text-gray-500">{new Date(v.generated_at).toLocaleString()}</p>
            </div>
            {prev && (
              <button
                type="button"
                onClick={() => onSelectVersions(prev.version, v.version)}
                className="rounded px-2 py-1 text-[11px] font-medium text-sky-600 hover:bg-sky-50 dark:text-sky-400 dark:hover:bg-sky-950"
              >
                Diff
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
