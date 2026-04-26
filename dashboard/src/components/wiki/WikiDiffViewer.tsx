import { Loader2 } from "lucide-react";
import ReactDiffViewer from "react-diff-viewer-continued";
import { useWikiDiff } from "../../hooks/useWikiDiff";

interface WikiDiffViewerProps {
  pageUid: string;
  fromVersion: number;
  toVersion: number;
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

export default function WikiDiffViewer({ pageUid, fromVersion, toVersion }: WikiDiffViewerProps) {
  const { data, isLoading, isError } = useWikiDiff(pageUid, fromVersion, toVersion);

  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <Loader2 className="size-5 animate-spin text-gray-400" />
      </div>
    );
  }

  if (isError || !data) {
    return <p className="py-4 text-center text-sm text-gray-500">Unable to load diff</p>;
  }

  const { oldValue, newValue } = buildSidesFromHunks(data.hunks);

  return (
    <div className="overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700">
      <ReactDiffViewer
        oldValue={oldValue}
        newValue={newValue}
        splitView
        leftTitle={`v${fromVersion}`}
        rightTitle={`v${toVersion}`}
      />
    </div>
  );
}
