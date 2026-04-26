import { useEffect, useId, useMemo, useState } from "react";
import {
  GitPullRequest,
  AlertTriangle,
  FileText,
  Plus,
  Trash2,
  Loader2,
} from "lucide-react";
import { useRepositories, useAnalyzeImpact, useFetchPrFiles } from "../api/hooks";
import type { AnalyzeImpactFile, AnalyzeImpactResponse, ImpactPage } from "../api/types";
import { Link } from "react-router-dom";
import { useI18n } from "../i18n/context";
import type { Translations } from "../i18n/types";
import { wikiHref, wikiSearchHref } from "../components/wiki/wikiRouteHelpers";
import { getErrorMessage } from "../utils/errorUtils";

type FileRow = { id: string; path: string; status: AnalyzeImpactFile["status"] };

const STATUSES: AnalyzeImpactFile["status"][] = ["added", "modified", "removed", "renamed"];

function statusLabel(t: Translations["prImpact"], s: AnalyzeImpactFile["status"]): string {
  switch (s) {
    case "added":
      return t.statusAdded;
    case "modified":
      return t.statusModified;
    case "removed":
      return t.statusRemoved;
    case "renamed":
      return t.statusRenamed;
    default:
      return s;
  }
}

/** v4 UUID when available; fallback for non-secure HTTP where `crypto.randomUUID` is missing or throws. */
function newRowId(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
  } catch {
    /* some browsers only expose randomUUID in secure contexts */
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

function newRow(): FileRow {
  return { id: newRowId(), path: "", status: "modified" };
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
  if (l.includes("high")) return "border-red-200 bg-red-50/90 dark:border-red-900/50 dark:bg-red-950/40";
  if (l.includes("medium")) return "border-amber-200 bg-amber-50/90 dark:border-amber-900/50 dark:bg-amber-950/40";
  if (l.includes("low")) return "border-emerald-200 bg-emerald-50/90 dark:border-emerald-900/50 dark:bg-emerald-950/40";
  return "border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/80";
}

function dotClass(level: string): string {
  const l = level.toLowerCase();
  if (l.includes("high")) return "bg-red-500";
  if (l.includes("medium")) return "bg-amber-500";
  if (l.includes("low")) return "bg-emerald-500";
  return "bg-gray-400";
}

export default function PrImpactPage() {
  const { t } = useI18n();
  const bulkId = useId();
  const repoSelectId = useId();
  const prUrlInputId = useId();
  const p = t.prImpact;

  const { data: reposData, isLoading: reposLoading } = useRepositories();
  const analyzeMutation = useAnalyzeImpact();
  const fetchPrMutation = useFetchPrFiles();

  const [repository, setRepository] = useState("");
  const [rows, setRows] = useState<FileRow[]>(() => [newRow()]);
  const [bulkText, setBulkText] = useState("");
  const [prUrl, setPrUrl] = useState("");
  const [fetchWarning, setFetchWarning] = useState<string | null>(null);
  const [result, setResult] = useState<AnalyzeImpactResponse | null>(null);

  const repositories = reposData?.repositories ?? [];

  useEffect(() => {
    if (!repository && repositories.length > 0) {
      setRepository(repositories[0].repository);
    }
  }, [repositories, repository]);

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
      if (p) parsed.push({ id: newRowId(), path: p.path, status: p.status });
    }
    if (parsed.length > 0) setRows(parsed);
  };

  const handleFetchFromUrl = () => {
    const u = prUrl.trim();
    if (!u) return;
    setFetchWarning(null);
    fetchPrMutation.mutate(
      { url: u },
      {
        onSuccess: (data) => {
          setResult(null);
          setFetchWarning(data.warning ?? null);
          const names = new Set(repositories.map((r) => r.repository));
          if (data.repository && names.has(data.repository)) {
            setRepository(data.repository);
          }
          const files = data.changed_files ?? [];
          if (files.length > 0) {
            setRows(files.map((f) => ({ id: newRowId(), path: f.path, status: f.status })));
          } else {
            setRows([newRow()]);
            if (!data.warning) setFetchWarning(p.fetchNoFiles);
          }
        },
      },
    );
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
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-sky-100 text-sky-600 dark:bg-sky-950/60 dark:text-sky-400">
          <GitPullRequest size={24} aria-hidden />
        </div>
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-gray-900 dark:text-gray-100">{p.title}</h1>
          <p className="mt-1 max-w-2xl text-sm text-gray-600 dark:text-gray-400">{p.subtitle}</p>
        </div>
      </div>

      <section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-900 dark:shadow-gray-950/50">
        <div className="space-y-4">
          <div>
            <label htmlFor={repoSelectId} className="mb-1.5 block text-sm font-medium text-gray-700 dark:text-gray-300">
              {p.repository}
            </label>
            <select
              id={repoSelectId}
              value={repository}
              onChange={(e) => setRepository(e.target.value)}
              disabled={reposLoading || repositories.length === 0}
              className="w-full max-w-md rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 outline-none ring-sky-500/30 focus:border-sky-400 focus:ring-2 disabled:opacity-60 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-sky-500 dark:focus:ring-sky-700"
            >
              {repositories.map((r) => (
                <option key={r.repository} value={r.repository}>
                  {r.repository}
                </option>
              ))}
            </select>
            {!reposLoading && repositories.length === 0 && (
              <p className="mt-2 text-sm text-amber-700 dark:text-amber-300">{p.noRepositories}</p>
            )}
          </div>

          <div className="rounded-lg border border-gray-200 bg-gray-50/50 p-4 dark:border-gray-600 dark:bg-gray-800/40">
            <label
              htmlFor={prUrlInputId}
              className="mb-1.5 block text-sm font-medium text-gray-700 dark:text-gray-300"
            >
              {p.prUrlLabel}
            </label>
            <div className="flex flex-wrap gap-2">
              <input
                id={prUrlInputId}
                type="url"
                inputMode="url"
                autoComplete="off"
                value={prUrl}
                onChange={(e) => setPrUrl(e.target.value)}
                placeholder={p.prUrlPlaceholder}
                className="min-w-[240px] flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 outline-none ring-sky-500/30 focus:border-sky-400 focus:ring-2 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 dark:focus:border-sky-500 dark:focus:ring-sky-700"
              />
              <button
                type="button"
                onClick={handleFetchFromUrl}
                disabled={fetchPrMutation.isPending || !prUrl.trim()}
                className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-sm font-medium text-sky-800 hover:bg-sky-100 disabled:opacity-50 dark:border-sky-800 dark:bg-sky-950/50 dark:text-sky-200 dark:hover:bg-sky-950/80"
              >
                {fetchPrMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
                {fetchPrMutation.isPending ? p.fetchingFromUrl : p.fetchFromUrl}
              </button>
            </div>
            {fetchWarning && (
              <p className="mt-2 text-sm text-amber-800 dark:text-amber-200">{fetchWarning}</p>
            )}
            {fetchPrMutation.isError && (
              <p className="mt-2 text-sm text-red-700 dark:text-red-300">
                {getErrorMessage(fetchPrMutation.error, t.common.unexpectedError)}
              </p>
            )}
          </div>

          <div>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">{p.changedFiles}</span>
              <button
                type="button"
                onClick={() => setRows((prev) => [...prev, newRow()])}
                className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-1.5 text-xs font-medium text-gray-800 hover:bg-gray-100 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
              >
                <Plus className="size-3.5" />
                {p.addFile}
              </button>
            </div>
            <ul className="space-y-2">
              {rows.map((row) => (
                <li
                  key={row.id}
                  className="flex flex-wrap items-center gap-2 rounded-lg border border-gray-100 bg-gray-50/80 px-3 py-2 dark:border-gray-700 dark:bg-gray-800/60"
                >
                  <input
                    type="text"
                    value={row.path}
                    onChange={(e) =>
                      setRows((prev) =>
                        prev.map((r) => (r.id === row.id ? { ...r, path: e.target.value } : r)),
                      )
                    }
                    placeholder={p.filePathPlaceholder}
                    className="min-w-[200px] flex-1 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 font-mono text-sm text-gray-900 outline-none ring-sky-500/30 focus:border-sky-400 focus:ring-2 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-sky-500 dark:focus:ring-sky-700"
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
                    className="rounded-md border border-gray-200 bg-white px-2 py-1.5 text-sm text-gray-900 outline-none ring-sky-500/30 focus:border-sky-400 focus:ring-2 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:focus:border-sky-500 dark:focus:ring-sky-700"
                  >
                    {STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {statusLabel(t.prImpact, s)}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => setRows((prev) => prev.filter((r) => r.id !== row.id))}
                    className="inline-flex items-center rounded-md p-1.5 text-gray-500 hover:bg-red-50 hover:text-red-600 dark:text-gray-400 dark:hover:bg-red-950/50 dark:hover:text-red-400"
                    aria-label={p.removeRow}
                  >
                    <Trash2 className="size-4" />
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-lg border border-dashed border-gray-200 bg-white p-4 dark:border-gray-600 dark:bg-gray-800/60">
            <label htmlFor={bulkId} className="mb-2 block text-xs font-medium text-gray-600 dark:text-gray-400">
              {p.bulkHint}
            </label>
            <textarea
              id={bulkId}
              value={bulkText}
              onChange={(e) => setBulkText(e.target.value)}
              rows={4}
              className="w-full resize-y rounded-lg border border-gray-200 bg-white px-3 py-2 font-mono text-xs text-gray-900 outline-none ring-sky-500/30 focus:border-sky-400 focus:ring-2 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 dark:focus:border-sky-500 dark:focus:ring-sky-700"
              placeholder={p.bulkPlaceholder}
            />
            <button
              type="button"
              onClick={applyBulk}
              className="mt-2 rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white"
            >
              {p.applyBulk}
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
              {analyzeMutation.isPending ? p.analyzing : p.analyze}
            </button>
            {changedFiles.length > 0 && (
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {p.fileCount.replace("{count}", String(changedFiles.length))}
              </span>
            )}
          </div>

          {analyzeMutation.isError && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
              {getErrorMessage(analyzeMutation.error, t.common.unexpectedError)}
            </div>
          )}
        </div>
      </section>

      {(summary || result) && (
        <section className="space-y-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
            <FileText className="size-4 text-gray-400 dark:text-gray-500" aria-hidden />
            {p.riskSummary}
          </h2>
          {summary && (
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl border border-red-100 bg-red-50/80 p-4 shadow-sm dark:border-red-900/40 dark:bg-red-950/40">
                <div className="text-xs font-medium text-red-800 dark:text-red-300">{p.highImpact}</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums text-red-900 dark:text-red-200">
                  {summary.high_impact}
                </div>
              </div>
              <div className="rounded-xl border border-amber-100 bg-amber-50/80 p-4 shadow-sm dark:border-amber-900/40 dark:bg-amber-950/40">
                <div className="text-xs font-medium text-amber-800 dark:text-amber-300">{p.mediumImpact}</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums text-amber-900 dark:text-amber-200">
                  {summary.medium_impact}
                </div>
              </div>
              <div className="rounded-xl border border-sky-100 bg-sky-50/80 p-4 shadow-sm dark:border-sky-900/40 dark:bg-sky-950/40">
                <div className="text-xs font-medium text-sky-800 dark:text-sky-300">{p.affectedPagesCount}</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums text-sky-900 dark:text-sky-200">
                  {summary.total_affected_pages}
                </div>
              </div>
            </div>
          )}

          <div>
            <h3 className="mb-3 text-sm font-semibold text-gray-900 dark:text-gray-100">{p.affectedWikiPages}</h3>
            {result?.affected_pages?.length ? (
              <ul className="space-y-3">
                {result.affected_pages.map((page: ImpactPage, i: number) => (
                  <li
                    key={`${page.wiki_page_path}-${i}`}
                    className={`rounded-xl border p-4 shadow-sm ${impactLevelStyle(page.impact_level)}`}
                  >
                    <div className="flex flex-wrap items-start gap-2">
                      <span
                        className={`mt-1 inline-block h-2 w-2 shrink-0 rounded-full ${dotClass(page.impact_level)}`}
                      />
                      <div className="min-w-0 flex-1">
                        <Link
                          to={wikiHref(page.wiki_page_path)}
                          className="inline-block font-mono text-sm font-semibold text-sky-700 hover:text-sky-900 hover:underline dark:text-sky-400 dark:hover:text-sky-300"
                        >
                          {page.wiki_page_path}
                        </Link>
                        <div className="mt-2 flex flex-wrap gap-2 text-xs">
                          <span className="rounded-full bg-white/80 px-2 py-0.5 font-medium text-gray-800 ring-1 ring-gray-200/80 dark:bg-gray-800/90 dark:text-gray-200 dark:ring-gray-600">
                            {page.impact_level}
                          </span>
                        </div>
                        <p className="mt-2 text-sm leading-relaxed text-gray-700 dark:text-gray-300">
                          <span className="font-medium text-gray-800 dark:text-gray-200">{p.reason}: </span>
                          {page.reason}
                        </p>
                        {(page.affected_entities ?? []).length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-1">
                            {(page.affected_entities ?? []).map((entity) => (
                              <Link
                                key={entity}
                                to={wikiSearchHref(entity)}
                                className="rounded bg-white/80 px-1.5 py-0.5 font-mono text-xs text-sky-700 ring-1 ring-gray-200/60 hover:bg-sky-50 hover:ring-sky-200/80 dark:bg-gray-800/90 dark:text-sky-400 dark:ring-gray-600 dark:hover:bg-sky-950/50 dark:hover:ring-sky-700"
                              >
                                {entity}
                              </Link>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-gray-500 dark:text-gray-400">{p.empty}</p>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
