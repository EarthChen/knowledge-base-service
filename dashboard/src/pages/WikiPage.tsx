import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  Activity,
  BookOpen,
  ChevronRight,
  FileOutput,
  LayoutGrid,
  Loader2,
  Network,
  RefreshCw,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useRepositories } from "../api/hooks";
import AskPanel from "../components/wiki/AskPanel";
import GraphInsightsPanel from "../components/wiki/GraphInsightsPanel";
import WikiContent from "../components/wiki/WikiContent";
import WikiExportPanel from "../components/wiki/WikiExportPanel";
import WikiLintPanel from "../components/wiki/WikiLintPanel";
import WikiSidebar from "../components/wiki/WikiSidebar";
import { useWikiPages } from "../hooks/useWikiPages";
import { useWikiPage } from "../hooks/useWikiPage";
import { wikiGenerate } from "../api/client";
import { useToast } from "../components/Toast";
import { useI18n } from "../i18n/context";

type WikiToolTab = "page" | "health" | "insights" | "export";

function parseWikiToolTab(raw: string | null): WikiToolTab {
  if (raw === "health" || raw === "insights" || raw === "export") return raw;
  return "page";
}

function decodeWikiPathSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

export default function WikiPage() {
  const params = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const repositoryRaw = params.repository;
  const repository = repositoryRaw
    ? decodeWikiPathSegment(repositoryRaw)
    : undefined;

  const splatRaw = (params["*"] as string | undefined) ?? "";
  const pagePath = splatRaw
    .split("/")
    .filter(Boolean)
    .map(decodeWikiPathSegment)
    .join("/");

  const [toolTab, setToolTabState] = useState<WikiToolTab>(() =>
    parseWikiToolTab(searchParams.get("tool")),
  );

  useEffect(() => {
    setToolTabState(parseWikiToolTab(searchParams.get("tool")));
  }, [searchParams]);

  const focusAsk = searchParams.get("focus");
  useEffect(() => {
    if (focusAsk !== "ask") return;
    if (!repository) {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete("focus");
          return next;
        },
        { replace: true },
      );
      return;
    }
    const id = window.setTimeout(() => {
      document.getElementById("wiki-ask-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete("focus");
          return next;
        },
        { replace: true },
      );
    }, 0);
    return () => window.clearTimeout(id);
  }, [repository, focusAsk, setSearchParams]);

  const reposQuery = useRepositories();
  const pagesQuery = useWikiPages(repository);
  const pageQuery = useWikiPage(repository, pagePath || undefined);
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { locale, t } = useI18n();
  const [regeneratePending, setRegeneratePending] = useState(false);

  async function handleRegenerateWiki() {
    if (!repository || regeneratePending) return;
    setRegeneratePending(true);
    try {
      const res = await wikiGenerate(repository, "repo", "structure", locale === "zh" ? "zh" : "en");
      const tid = res.task_id ? String(res.task_id) : "";
      const msg = tid
        ? t.wiki.regenerateStartedWithTask.replace("{taskId}", tid)
        : t.wiki.regenerateStarted;
      toast("success", msg);
      await queryClient.invalidateQueries({ queryKey: ["wiki"] });
    } catch (e) {
      toast("error", e instanceof Error ? e.message : String(e));
    } finally {
      setRegeneratePending(false);
    }
  }

  if (!repository) {
    const repos = reposQuery.data?.repositories ?? [];
    const pendingQuery = searchParams.get("q") ?? "";
    return (
      <div className="mx-auto max-w-3xl space-y-6">
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-700 dark:bg-gray-900">
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-sky-50 text-sky-600 dark:bg-sky-950 dark:text-sky-400">
              <BookOpen size={24} aria-hidden />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{t.wiki.title}</h2>
              <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">{t.wiki.browseDescription}</p>
              {pendingQuery && (
                <p className="mt-2 rounded-md bg-sky-50 px-3 py-2 text-sm text-sky-700 dark:bg-sky-950 dark:text-sky-300">
                  {t.wiki.pendingSearchNotice.replace("{query}", pendingQuery)}
                </p>
              )}
            </div>
          </div>
        </div>

        {reposQuery.isLoading && (
          <p className="text-sm text-gray-500 dark:text-gray-400">{t.wiki.loadingRepositories}</p>
        )}
        {reposQuery.isError && (
          <p className="text-sm text-red-600 dark:text-red-400">
            {(reposQuery.error as Error).message}
          </p>
        )}
        {!reposQuery.isLoading && repos.length === 0 && (
          <p className="text-sm text-gray-600 dark:text-gray-400">
            {t.wiki.noRepositoriesFound}{" "}
            <Link to="/repositories" className="text-sky-700 underline dark:text-sky-400">
              {t.wiki.addOrIndexRepository}
            </Link>{" "}
            {t.wiki.addOrIndexRepositorySuffix}
          </p>
        )}
        {repos.length > 0 && (
          <ul className="grid gap-3 sm:grid-cols-2">
            {repos.map((r) => (
              <li key={r.repository}>
                <Link
                  to={`/wiki/${encodeURIComponent(r.repository)}${pendingQuery ? `?q=${encodeURIComponent(pendingQuery)}` : ""}`}
                  className="flex items-center justify-between rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm transition-colors hover:border-sky-200 hover:bg-sky-50/40 dark:border-gray-700 dark:bg-gray-900 dark:hover:border-sky-800 dark:hover:bg-sky-950/30"
                >
                  <span className="font-medium text-gray-900 dark:text-gray-100">{r.repository}</span>
                  <ChevronRight size={18} className="text-gray-400 dark:text-gray-500" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  const pages = pagesQuery.data?.pages ?? [];
  const contentError =
    pagePath && pageQuery.isError
      ? pageQuery.error instanceof Error
        ? pageQuery.error
        : new Error(String(pageQuery.error))
      : null;

  const setToolTab = (t: WikiToolTab) => {
    setToolTabState(t);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (t === "page") next.delete("tool");
        else next.set("tool", t);
        return next;
      },
      { replace: true },
    );
  };

  const tabBtn = (id: WikiToolTab, label: string, icon: ReactNode) => (
    <button
      key={id}
      type="button"
      onClick={() => setToolTab(id)}
      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
        toolTab === id
          ? "bg-sky-100 text-sky-800 ring-1 ring-sky-200 dark:bg-sky-950 dark:text-sky-200 dark:ring-sky-800"
          : "text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
      }`}
    >
      {icon}
      {label}
    </button>
  );

  return (
    <div className="flex min-h-[min(70vh,860px)] flex-col gap-4 lg:flex-row lg:items-stretch">
      <WikiSidebar
        repository={repository}
        pages={pages}
        activePath={pagePath}
        pagesLoading={pagesQuery.isLoading}
        pagesError={
          pagesQuery.error instanceof Error
            ? pagesQuery.error
            : pagesQuery.error
              ? new Error(String(pagesQuery.error))
              : null
        }
      />

      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 shadow-sm dark:border-gray-700 dark:bg-gray-900">
          <div className="flex flex-wrap gap-2">
            {tabBtn("page", t.wiki.tabPage, <LayoutGrid size={14} className="text-sky-600 dark:text-sky-400" aria-hidden />)}
            {tabBtn("health", t.wiki.tabHealth, <Activity size={14} className="text-emerald-600 dark:text-emerald-400" aria-hidden />)}
            {tabBtn("insights", t.wiki.tabInsights, <Network size={14} className="text-violet-600 dark:text-violet-400" aria-hidden />)}
            {tabBtn("export", t.wiki.tabExport, <FileOutput size={14} className="text-sky-600 dark:text-sky-400" aria-hidden />)}
          </div>
          <button
            type="button"
            onClick={handleRegenerateWiki}
            disabled={regeneratePending}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-900 hover:bg-amber-100 disabled:opacity-50 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-200 dark:hover:bg-amber-950"
          >
            {regeneratePending ? (
              <Loader2 size={14} className="animate-spin" aria-hidden />
            ) : (
              <RefreshCw size={14} aria-hidden />
            )}
            {t.wiki.regenerate}
          </button>
        </div>

        {toolTab === "page" && (
          <>
            <WikiContent
              repository={repository}
              pagePath={pagePath}
              detail={pageQuery.data}
              isLoading={Boolean(pagePath) && pageQuery.isLoading}
              error={contentError}
            />
            <AskPanel repository={repository} />
          </>
        )}

        {toolTab === "health" && <WikiLintPanel repository={repository} />}

        {toolTab === "insights" && <GraphInsightsPanel repository={repository} />}

        {toolTab === "export" && <WikiExportPanel key={repository} repository={repository} />}
      </div>
    </div>
  );
}
