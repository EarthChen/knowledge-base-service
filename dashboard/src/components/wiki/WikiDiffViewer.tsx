import { Loader2 } from "lucide-react";
import ReactDiffViewer from "react-diff-viewer-continued";
import { useWikiDiff } from "../../hooks/useWikiDiff";
import { useI18n } from "../../i18n/context";

interface WikiDiffViewerProps {
  businessId: string;
  pageUid: string;
  fromVersion: number;
  toVersion: number;
  onClose?: () => void;
}

function buildSidesFromHunks(
  hunks: Array<{ content: string }>,
): { oldValue: string; newValue: string } {
  let oldValue = "";
  let newValue = "";
  for (const h of hunks) {
    const lines = h.content.split("\n");
    const oldLines = lines
      .filter((l) => l.startsWith("-") || l.startsWith(" "))
      .map((l) => l.slice(1));
    const newLines = lines
      .filter((l) => l.startsWith("+") || l.startsWith(" "))
      .map((l) => l.slice(1));
    if (oldLines.length) {
      oldValue += (oldValue ? "\n" : "") + oldLines.join("\n");
    }
    if (newLines.length) {
      newValue += (newValue ? "\n" : "") + newLines.join("\n");
    }
  }
  return { oldValue, newValue };
}

export default function WikiDiffViewer({
  businessId,
  pageUid,
  fromVersion,
  toVersion,
  onClose,
}: WikiDiffViewerProps) {
  const { t } = useI18n();
  const { data, isLoading, isError } = useWikiDiff(businessId, pageUid, fromVersion, toVersion);

  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <Loader2 className="size-5 animate-spin text-gray-400" />
      </div>
    );
  }

  if (isError || !data) {
    return <p className="py-4 text-center text-sm text-gray-500">{t.wiki.diffLoadError}</p>;
  }

  const { oldValue, newValue } = buildSidesFromHunks(data.hunks);
  const leftTitle = t.wiki.versionBadge.replace("{version}", String(fromVersion));
  const rightTitle = t.wiki.versionBadge.replace("{version}", String(toVersion));

  return (
    <div className="overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700">
      {onClose ? (
        <div className="flex items-center justify-between gap-2 border-b border-gray-200 bg-gray-50 px-3 py-2 dark:border-gray-700 dark:bg-gray-800/80">
          <span className="text-xs font-medium text-gray-700 dark:text-gray-300">
            {t.wiki.diffComparing} {leftTitle} {t.wiki.diffWith} {rightTitle}
          </span>
          <button
            type="button"
            onClick={onClose}
            className="rounded px-2 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100 dark:text-sky-400 dark:hover:bg-sky-950"
          >
            {t.wiki.diffClose}
          </button>
        </div>
      ) : null}
      <ReactDiffViewer
        oldValue={oldValue}
        newValue={newValue}
        splitView
        leftTitle={leftTitle}
        rightTitle={rightTitle}
      />
    </div>
  );
}
