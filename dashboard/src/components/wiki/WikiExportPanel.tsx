import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, FileOutput, Loader2, Play } from "lucide-react";
import { useMemo, useState } from "react";
import { wikiExportExecute, wikiExportPreview, ApiError } from "../../api/client";
import type { WikiExportDiff, WikiExportResult } from "../../api/types";

type Props = {
  repository: string;
};

type Step = "preview" | "execute";

function actionBadge(action: WikiExportDiff["action"]): string {
  if (action === "create") return "bg-emerald-100 text-emerald-900 ring-emerald-200";
  if (action === "update") return "bg-sky-100 text-sky-900 ring-sky-200";
  return "bg-gray-100 text-gray-700 ring-gray-200";
}

export default function WikiExportPanel({ repository }: Props) {
  const [targetDir, setTargetDir] = useState("");
  const [step, setStep] = useState<Step>("preview");
  const [previewResult, setPreviewResult] = useState<WikiExportResult | null>(null);
  const [executeResult, setExecuteResult] = useState<WikiExportResult | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const previewMutation = useMutation<WikiExportResult, Error, string>({
    mutationFn: (dir) => wikiExportPreview(repository, dir),
    onSuccess: (data) => {
      setPreviewResult(data);
      setExecuteResult(null);
      const next = new Set<string>();
      for (const d of data.diffs) {
        if (d.action === "create" || d.action === "update") next.add(d.file_path);
      }
      setSelected(next);
      setStep("execute");
    },
  });

  const executeMutation = useMutation<WikiExportResult, Error, { dir: string; files: string[] }>({
    mutationFn: ({ dir, files }) => wikiExportExecute(repository, dir, files),
    onSuccess: (data) => {
      setExecuteResult(data);
    },
  });

  const exportablePaths = useMemo(() => {
    if (!previewResult) return [];
    return previewResult.diffs
      .filter((d) => d.action === "create" || d.action === "update")
      .map((d) => d.file_path);
  }, [previewResult]);

  const togglePath = (path: string, action: WikiExportDiff["action"]) => {
    if (action === "skip") return;
    setSelected((prev) => {
      const n = new Set(prev);
      if (n.has(path)) n.delete(path);
      else n.add(path);
      return n;
    });
  };

  const toggleAllExportable = (on: boolean) => {
    if (on) setSelected(new Set(exportablePaths));
    else setSelected(new Set());
  };

  const handlePreview = () => {
    const dir = targetDir.trim();
    if (!dir) return;
    previewMutation.mutate(dir);
  };

  const handleExecute = () => {
    const dir = targetDir.trim();
    if (!dir || !previewResult) return;
    const files = Array.from(selected);
    if (files.length === 0) return;
    executeMutation.mutate({ dir, files });
  };

  const backToPreviewInput = () => {
    setStep("preview");
    setPreviewResult(null);
    setExecuteResult(null);
    previewMutation.reset();
    executeMutation.reset();
  };

  return (
    <section className="rounded-xl border border-gray-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-gray-900">
          <FileOutput size={18} className="text-sky-600" aria-hidden />
          Wiki export
        </div>
        {step === "execute" && (
          <button
            type="button"
            onClick={backToPreviewInput}
            className="inline-flex items-center gap-1 text-xs font-medium text-sky-700 hover:underline"
          >
            <ArrowLeft className="size-3.5" aria-hidden />
            New preview
          </button>
        )}
      </div>

      <div className="space-y-4 px-4 py-4">
        <p className="text-xs text-gray-500">
          Preview and write markdown to a local directory (
          <code className="rounded bg-gray-100 px-1">export/preview</code>,{" "}
          <code className="rounded bg-gray-100 px-1">export/execute</code>
          ). Requires editor role when the API enforces RBAC.
        </p>

        <div>
          <label className="block text-xs font-semibold uppercase tracking-wide text-gray-500">
            Target directory
          </label>
          <input
            value={targetDir}
            onChange={(e) => setTargetDir(e.target.value)}
            disabled={step === "execute" && Boolean(previewResult)}
            placeholder="/absolute/path/to/repo/docs"
            className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 font-mono text-sm outline-none ring-sky-500/30 focus:border-sky-400 focus:ring-2 disabled:bg-gray-50"
          />
        </div>

        {step === "preview" && (
          <button
            type="button"
            onClick={handlePreview}
            disabled={previewMutation.isPending || !targetDir.trim()}
            className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
          >
            {previewMutation.isPending ? (
              <Loader2 className="size-4 animate-spin" aria-hidden />
            ) : null}
            Preview export
          </button>
        )}

        {previewMutation.isError && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
            {previewMutation.error instanceof ApiError && previewMutation.error.status === 403
              ? "Forbidden: export requires an editor token when RBAC is enabled."
              : previewMutation.error instanceof ApiError
                ? previewMutation.error.message
                : previewMutation.error.message}
          </div>
        )}

        {step === "execute" && previewResult && (
          <>
            <div className="flex flex-wrap gap-2 text-xs">
              <span className="rounded-full bg-gray-100 px-2.5 py-1 font-medium text-gray-700 ring-1 ring-gray-200">
                Files {previewResult.total_files}
              </span>
              <span className="rounded-full bg-emerald-100 px-2.5 py-1 font-medium text-emerald-900 ring-1 ring-emerald-200">
                Create {previewResult.created}
              </span>
              <span className="rounded-full bg-sky-100 px-2.5 py-1 font-medium text-sky-900 ring-1 ring-sky-200">
                Update {previewResult.updated}
              </span>
              <span className="rounded-full bg-gray-200/80 px-2.5 py-1 font-medium text-gray-700 ring-1 ring-gray-300">
                Skip {previewResult.skipped}
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-3 text-xs">
              <button
                type="button"
                onClick={() => toggleAllExportable(true)}
                className="font-medium text-sky-700 hover:underline"
              >
                Select all writable
              </button>
              <button
                type="button"
                onClick={() => toggleAllExportable(false)}
                className="font-medium text-gray-600 hover:underline"
              >
                Clear selection
              </button>
            </div>

            <div className="max-h-[min(50vh,420px)] overflow-y-auto rounded-lg border border-gray-100">
              <table className="w-full text-left text-sm">
                <thead className="sticky top-0 bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
                  <tr>
                    <th className="w-10 px-2 py-2"> </th>
                    <th className="px-2 py-2">File</th>
                    <th className="px-2 py-2">Action</th>
                    <th className="px-2 py-2">Summary</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {previewResult.diffs.map((d) => {
                    const canSelect = d.action === "create" || d.action === "update";
                    const checked = selected.has(d.file_path);
                    return (
                      <tr key={d.file_path} className="bg-white/90">
                        <td className="px-2 py-2 align-top">
                          <input
                            type="checkbox"
                            className="rounded border-gray-300 text-sky-600 focus:ring-sky-500"
                            checked={checked}
                            disabled={!canSelect}
                            onChange={() => togglePath(d.file_path, d.action)}
                            aria-label={`Select ${d.file_path}`}
                          />
                        </td>
                        <td className="px-2 py-2 align-top font-mono text-xs text-gray-900">
                          {d.file_path}
                        </td>
                        <td className="px-2 py-2 align-top">
                          <span
                            className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ring-1 ${actionBadge(d.action)}`}
                          >
                            {d.action}
                          </span>
                        </td>
                        <td className="px-2 py-2 align-top text-xs text-gray-600">{d.diff_summary}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {executeMutation.isError && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {executeMutation.error instanceof ApiError && executeMutation.error.status === 403
                  ? "Forbidden: export requires an editor token when RBAC is enabled."
                  : executeMutation.error instanceof ApiError
                    ? executeMutation.error.message
                    : executeMutation.error.message}
              </div>
            )}

            <button
              type="button"
              onClick={handleExecute}
              disabled={executeMutation.isPending || selected.size === 0}
              className="inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              {executeMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Play className="size-4" aria-hidden />
              )}
              Export selected
            </button>

            {selected.size === 0 && (
              <p className="text-xs text-amber-700">Select at least one create/update row to export.</p>
            )}

            {executeResult && (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50/80 px-3 py-3 text-sm text-emerald-950">
                <p className="font-semibold">Export finished</p>
                <p className="mt-1 text-xs">
                  Created {executeResult.created}, updated {executeResult.updated}, skipped{" "}
                  {executeResult.skipped} (post-run scan).
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
