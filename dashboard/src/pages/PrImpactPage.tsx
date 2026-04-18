import { useEffect, useId, useMemo, useState } from "react";
import {
  GitPullRequest,
  AlertTriangle,
  FileText,
  Plus,
  Trash2,
  Loader2,
} from "lucide-react";
import { useRepositories, useAnalyzeImpact } from "../api/hooks";
import type { AnalyzeImpactFile, AnalyzeImpactResponse, ImpactPage } from "../api/types";
import { useI18n } from "../i18n/context";

type FileRow = { id: string; path: string; status: AnalyzeImpactFile["status"] };

const STATUSES: AnalyzeImpactFile["status"][] = ["added", "modified", "removed", "renamed"];

function newRow(): FileRow {
  return { id: crypto.randomUUID(), path: "", status: "modified" };
}

function parseBulkLine(line: string): { path: string; status: AnalyzeImpactFile["status"] } | null {
  const trimmed = line.trim();
  if (!trimmed) return null;
  const colon = trimmed.indexOf(":");
  if (colon <= 0) return null;
  const status = trimmed.slice(0, colon).trim().toLowerCase();
  const path = trimmed.slice(colon + 1).trim();
  if (!path) return null;
  if (!STATUSES.includes(status as AnalyzeImpactFile["status"])) return null;
  return { path, status: status as AnalyzeImpactFile["status"] };
}

function impactLevelStyle(level: string): string {
  const l = level.toLowerCase();
  if (l.includes("high")) return "border-red-200 bg-red-50/90";
  if (l.includes("medium")) return "border-amber-200 bg-amber-50/90";
  if (l.includes("low")) return "border-emerald-200 bg-emerald-50/90";
  return "border-gray-200 bg-gray-50";
}

function dotClass(level: string): string {
  const l = level.toLowerCase();
  if (l.includes("high")) return "bg-red-500";
  if (l.includes("medium")) return "bg-amber-500";
  if (l.includes("low")) return "bg-emerald-500";
  return "bg-gray-400";
}

export default function PrImpactPage() {
  const { locale } = useI18n();
  const isZh = locale === "zh";
  const bulkId = useId();
  const repoSelectId = useId();

  const { data: reposData, isLoading: reposLoading } = useRepositories();
  const analyzeMutation = useAnalyzeImpact();

  const [repository, setRepository] = useState("");
  const [rows, setRows] = useState<FileRow[]>(() => [newRow()]);
  const [bulkText, setBulkText] = useState("");
  const [result, setResult] = useState<AnalyzeImpactResponse | null>(null);

  const repositories = reposData?.repositories ?? [];

  useEffect(() => {
    if (!repository && repositories.length > 0) {
      setRepository(repositories[0].repository);
    }
  }, [repositories, repository]);

  const labels = useMemo(
    () => ({
      title: isZh ? "PR 影响分析" : "PR impact analysis",
      subtitle: isZh
        ? "选择仓库并列出变更文件，评估对 Wiki 页面的影响范围"
        : "Select a repository and list changed files to assess wiki page impact.",
      repo: isZh ? "仓库" : "Repository",
      files: isZh ? "变更文件" : "Changed files",
      addFile: isZh ? "添加文件" : "Add file",
      bulkHint: isZh
        ? "批量输入（每行 status:path，例如 modified:src/app.ts）"
        : "Bulk paste (one per line: status:path, e.g. modified:src/app.ts)",
      applyBulk: isZh ? "应用批量输入" : "Apply bulk",
      analyze: isZh ? "分析影响" : "Analyze impact",
      analyzing: isZh ? "分析中…" : "Analyzing…",
      summary: isZh ? "风险摘要" : "Risk summary",
      high: isZh ? "高影响" : "High impact",
      medium: isZh ? "中影响" : "Medium impact",
      totalPages: isZh ? "受影响页面" : "Affected pages",
      affectedTitle: isZh ? "受影响页面" : "Affected wiki pages",
      empty: isZh ? "暂无结果，提交变更文件后开始分析。" : "No results yet. Add files and run analysis.",
      pagePath: isZh ? "页面路径" : "Page path",
      reason: isZh ? "原因" : "Reason",
      noRepo: isZh ? "暂无可用仓库。" : "No repositories available.",
    }),
    [isZh],
  );

  const changedFiles: AnalyzeImpactFile[] = useMemo(
    () =>
      rows
        .map((r) => ({ path: r.path.trim(), status: r.status }))
        .filter((f) => f.path.length > 0),
    [rows],
  );

  const applyBulk = () => {
    const parsed: FileRow[] = [];
    for (const line of bulkText.split(/\r?\n/)) {
      const p = parseBulkLine(line);
      if (p) parsed.push({ id: crypto.randomUUID(), path: p.path, status: p.status });
    }
    if (parsed.length > 0) setRows(parsed);
  };

  const handleAnalyze = () => {
    if (!repository.trim() || changedFiles.length === 0) return;
    setResult(null);
    analyzeMutation.mutate(
      { repository: repository.trim(), changed_files: changedFiles },
      {
        onSuccess: (data) => setResult(data),
      },
    );
  };

  const summary = result?.summary;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex flex-wrap items-start gap-4">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-sky-100 text-sky-600">
          <GitPullRequest size={24} aria-hidden />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-gray-900">{labels.title}</h1>
          <p className="mt-1 max-w-2xl text-sm text-gray-600">{labels.subtitle}</p>
        </div>
      </div>

      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="space-y-4">
          <div>
            <label htmlFor={repoSelectId} className="mb-1.5 block text-sm font-medium text-gray-700">
              {labels.repo}
            </label>
            <select
              id={repoSelectId}
              value={repository}
              onChange={(e) => setRepository(e.target.value)}
              disabled={reposLoading || repositories.length === 0}
              className="w-full max-w-md rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm outline-none ring-sky-500/30 focus:border-sky-400 focus:ring-2 disabled:opacity-60"
            >
              {repositories.map((r) => (
                <option key={r.repository} value={r.repository}>
                  {r.repository}
                </option>
              ))}
            </select>
            {!reposLoading && repositories.length === 0 && (
              <p className="mt-2 text-sm text-amber-700">{labels.noRepo}</p>
            )}
          </div>

          <div>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium text-gray-700">{labels.files}</span>
              <button
                type="button"
                onClick={() => setRows((prev) => [...prev, newRow()])}
                className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-1.5 text-xs font-medium text-gray-800 hover:bg-gray-100"
              >
                <Plus className="size-3.5" />
                {labels.addFile}
              </button>
            </div>
            <ul className="space-y-2">
              {rows.map((row) => (
                <li
                  key={row.id}
                  className="flex flex-wrap items-center gap-2 rounded-lg border border-gray-100 bg-gray-50/80 px-3 py-2"
                >
                  <input
                    type="text"
                    value={row.path}
                    onChange={(e) =>
                      setRows((prev) =>
                        prev.map((r) => (r.id === row.id ? { ...r, path: e.target.value } : r)),
                      )
                    }
                    placeholder={isZh ? "文件路径" : "File path"}
                    className="min-w-[200px] flex-1 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 font-mono text-sm outline-none ring-sky-500/30 focus:border-sky-400 focus:ring-2"
                  />
                  <select
                    value={row.status}
                    onChange={(e) =>
                      setRows((prev) =>
                        prev.map((r) =>
                          r.id === row.id
                            ? { ...r, status: e.target.value as AnalyzeImpactFile["status"] }
                            : r,
                        ),
                      )
                    }
                    className="rounded-md border border-gray-200 bg-white px-2 py-1.5 text-sm outline-none ring-sky-500/30 focus:border-sky-400 focus:ring-2"
                  >
                    {STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => setRows((prev) => prev.filter((r) => r.id !== row.id))}
                    className="inline-flex items-center rounded-md p-1.5 text-gray-500 hover:bg-red-50 hover:text-red-600"
                    aria-label={isZh ? "删除" : "Remove"}
                  >
                    <Trash2 className="size-4" />
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-lg border border-dashed border-gray-200 bg-white p-4">
            <label htmlFor={bulkId} className="mb-2 block text-xs font-medium text-gray-600">
              {labels.bulkHint}
            </label>
            <textarea
              id={bulkId}
              value={bulkText}
              onChange={(e) => setBulkText(e.target.value)}
              rows={4}
              className="w-full resize-y rounded-lg border border-gray-200 px-3 py-2 font-mono text-xs outline-none ring-sky-500/30 focus:border-sky-400 focus:ring-2"
              placeholder={"modified:src/foo.ts\nadded:src/bar.ts"}
            />
            <button
              type="button"
              onClick={applyBulk}
              className="mt-2 rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800"
            >
              {labels.applyBulk}
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-3 pt-1">
            <button
              type="button"
              onClick={handleAnalyze}
              disabled={
                analyzeMutation.isPending ||
                !repository.trim() ||
                changedFiles.length === 0 ||
                reposLoading
              }
              className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-sky-500 disabled:opacity-50"
            >
              {analyzeMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <AlertTriangle className="size-4" />
              )}
              {analyzeMutation.isPending ? labels.analyzing : labels.analyze}
            </button>
            {changedFiles.length > 0 && (
              <span className="text-xs text-gray-500">
                {changedFiles.length} {isZh ? "个文件" : "file(s)"}
              </span>
            )}
          </div>

          {analyzeMutation.isError && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              {(analyzeMutation.error as Error)?.message ?? String(analyzeMutation.error)}
            </div>
          )}
        </div>
      </section>

      {(summary || result) && (
        <section className="space-y-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-gray-500">
            <FileText className="size-4 text-gray-400" aria-hidden />
            {labels.summary}
          </h2>
          {summary && (
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl border border-red-100 bg-red-50/80 p-4 shadow-sm">
                <div className="text-xs font-medium text-red-800">{labels.high}</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums text-red-900">
                  {summary.high_impact}
                </div>
              </div>
              <div className="rounded-xl border border-amber-100 bg-amber-50/80 p-4 shadow-sm">
                <div className="text-xs font-medium text-amber-800">{labels.medium}</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums text-amber-900">
                  {summary.medium_impact}
                </div>
              </div>
              <div className="rounded-xl border border-sky-100 bg-sky-50/80 p-4 shadow-sm">
                <div className="text-xs font-medium text-sky-800">{labels.totalPages}</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums text-sky-900">
                  {summary.total_affected_pages}
                </div>
              </div>
            </div>
          )}

          <div>
            <h3 className="mb-3 text-sm font-semibold text-gray-900">{labels.affectedTitle}</h3>
            {result?.affected_pages?.length ? (
              <ul className="space-y-3">
                {result.affected_pages.map((p: ImpactPage, i: number) => (
                  <li
                    key={`${p.wiki_page_path}-${i}`}
                    className={`rounded-xl border p-4 shadow-sm ${impactLevelStyle(p.impact_level)}`}
                  >
                    <div className="flex flex-wrap items-start gap-2">
                      <span
                        className={`mt-1 inline-block h-2 w-2 shrink-0 rounded-full ${dotClass(p.impact_level)}`}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="font-mono text-sm font-semibold text-gray-900">{p.wiki_page_path}</div>
                        <div className="mt-2 flex flex-wrap gap-2 text-xs">
                          <span className="rounded-full bg-white/80 px-2 py-0.5 font-medium text-gray-800 ring-1 ring-gray-200/80">
                            {p.impact_level}
                          </span>
                        </div>
                        <p className="mt-2 text-sm leading-relaxed text-gray-700">
                          <span className="font-medium text-gray-800">{labels.reason}: </span>
                          {p.reason}
                        </p>
                        {p.affected_entities.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-1">
                            {p.affected_entities.map((entity) => (
                              <code
                                key={entity}
                                className="rounded bg-white/80 px-1.5 py-0.5 font-mono text-xs text-sky-700 ring-1 ring-gray-200/60"
                              >
                                {entity}
                              </code>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-gray-500">{labels.empty}</p>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
