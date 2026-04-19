import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  BookOpen,
  ChevronDown,
  ChevronUp,
  FolderOpen,
  GitMerge,
  Loader2,
} from "lucide-react";
import type { WikiPageDetail, WikiSourceLocation } from "../../hooks/wikiTypes";
import MarkdownRenderer from "./MarkdownRenderer";
import WikiBreadcrumbs from "./WikiBreadcrumbs";
import { buildIdeHref, type EditorId } from "./editorLinks";
import { EDITOR_PREF_KEY } from "./SourceLink";
import { useAnalyzeImpact } from "../../api/hooks";
import type { AnalyzeImpactResponse } from "../../api/types";
import { useI18n } from "../../i18n/context";

type Props = {
  repository: string;
  pagePath: string;
  detail: WikiPageDetail | undefined;
  isLoading: boolean;
  error: Error | null;
};

function readEditorPref(): EditorId {
  try {
    const v = localStorage.getItem(EDITOR_PREF_KEY);
    if (v === "cursor" || v === "idea" || v === "vscode") return v;
  } catch {
    /* ignore */
  }
  return "cursor";
}

function wikiHref(repository: string, path: string): string {
  const er = encodeURIComponent(repository);
  const ep = path
    .split("/")
    .filter(Boolean)
    .map((s) => encodeURIComponent(s))
    .join("/");
  return `/wiki/${er}/${ep}`;
}

function SourceLocRow({ loc, repository }: { loc: WikiSourceLocation; repository: string }) {
  const editor = readEditorPref();
  const href = buildIdeHref(editor, repository, loc.file_path, loc.start_line);
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">
      <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs text-gray-800">
        {loc.fqn}
      </code>
      <a
        href={href}
        className="text-sky-700 underline decoration-sky-200 underline-offset-2 hover:text-sky-900"
      >
        {loc.file_path}:{loc.start_line}–{loc.end_line}
      </a>
    </li>
  );
}

function chainCardClass(level: string): string {
  const l = level.toLowerCase();
  if (l.includes("high")) return "border-red-200 bg-red-50/90";
  if (l.includes("medium")) return "border-amber-200 bg-amber-50/90";
  if (l.includes("low")) return "border-emerald-200 bg-emerald-50/90";
  return "border-gray-200 bg-gray-50";
}

function CallChainSection({
  repository,
  detail,
}: {
  repository: string;
  detail: WikiPageDetail;
}) {
  const { locale } = useI18n();
  const isZh = locale === "zh";
  const [expanded, setExpanded] = useState(false);
  const analyzeMutation = useAnalyzeImpact();
  const [impactResult, setImpactResult] = useState<AnalyzeImpactResponse | null>(null);

  const fqns = useMemo(
    () => detail.source_locations.map((loc) => loc.fqn).filter(Boolean),
    [detail.source_locations],
  );

  const changedFiles = useMemo(() => {
    const map = new Map<string, { path: string; status: "modified" }>();
    for (const loc of detail.source_locations) {
      if (!loc.file_path) continue;
      map.set(loc.file_path, { path: loc.file_path, status: "modified" });
    }
    return Array.from(map.values());
  }, [detail.source_locations]);

  if (!detail.source_locations?.length) return null;

  const labels = {
    title: isZh ? "调用链 & 影响范围" : "Call chain & impact",
    fqns: isZh ? "符号（FQN）" : "Symbols (FQN)",
    viewImpact: isZh ? "查看调用链 / 分析影响" : "View impact",
    analyzing: isZh ? "分析中…" : "Analyzing…",
    affected: isZh ? "受影响页面" : "Affected pages",
    empty: isZh ? "暂无受影响页面。" : "No affected pages.",
    impact: isZh ? "影响" : "Impact",
  };

  const handleAnalyze = () => {
    setImpactResult(null);
    analyzeMutation.mutate(
      { repository, changed_files: changedFiles },
      {
        onSuccess: (data) => setImpactResult(data),
      },
    );
  };

  return (
    <section className="mt-10 border-t border-gray-100 pt-8">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between gap-3 rounded-lg px-1 py-2 text-left hover:bg-gray-50/80"
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-gray-900">
          <GitMerge size={18} className="text-violet-600" aria-hidden />
          {labels.title}
        </span>
        {expanded ? <ChevronUp size={18} className="text-gray-500" /> : <ChevronDown size={18} className="text-gray-500" />}
      </button>

      {expanded && (
        <div className="mt-3 space-y-4 rounded-xl border border-gray-100 bg-gray-50/60 p-4 shadow-inner">
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
              {labels.fqns}
            </h4>
            <ul className="flex flex-wrap gap-2">
              {fqns.map((fqn, i) => (
                <li key={`${fqn}-${i}`}>
                  <code className="rounded-md bg-white px-2 py-1 font-mono text-[11px] text-gray-800 ring-1 ring-gray-200/80">
                    {fqn}
                  </code>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={handleAnalyze}
              disabled={analyzeMutation.isPending || changedFiles.length === 0}
              className="inline-flex items-center gap-2 rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-violet-500 disabled:opacity-50"
            >
              {analyzeMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <GitMerge className="size-4" aria-hidden />
              )}
              {analyzeMutation.isPending ? labels.analyzing : labels.viewImpact}
            </button>
          </div>

          {analyzeMutation.isError && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {(analyzeMutation.error as Error)?.message ?? String(analyzeMutation.error)}
            </div>
          )}

          {impactResult && (
            <div>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                {labels.affected}
              </h4>
              {impactResult.affected_pages?.length ? (
                <ul className="space-y-2">
                  {impactResult.affected_pages.map((p, i) => (
                    <li
                      key={`${p.wiki_page_path}-${i}`}
                      className={`rounded-lg border p-3 shadow-sm ${chainCardClass(p.impact_level)}`}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                          <Link
                            to={wikiHref(repository, p.wiki_page_path)}
                            className="inline-block truncate font-mono text-sm font-medium text-sky-700 underline decoration-sky-200"
                          >
                            {p.wiki_page_path}
                          </Link>
                          {p.affected_entities.length > 0 && (
                            <div className="mt-1 flex flex-wrap gap-1">
                              {p.affected_entities.map((e) => (
                                <code key={e} className="rounded bg-white/80 px-1 py-0.5 text-xs text-gray-700">{e}</code>
                              ))}
                            </div>
                          )}
                        </div>
                        <span className="shrink-0 rounded-full bg-white/90 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-700 ring-1 ring-gray-200">
                          {labels.impact}: {p.impact_level}
                        </span>
                      </div>
                      {p.reason && (
                        <p className="mt-2 text-xs leading-relaxed text-gray-700">{p.reason}</p>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-gray-600">{labels.empty}</p>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function formatGeneratedAt(iso: string | null | undefined, locale: string): string | null {
  if (!iso || !String(iso).trim()) return null;
  try {
    return new Date(iso).toLocaleString(locale === "zh" ? "zh-CN" : undefined);
  } catch {
    return iso;
  }
}

export default function WikiContent({
  repository,
  pagePath,
  detail,
  isLoading,
  error,
}: Props) {
  const { locale, t } = useI18n();
  const title =
    detail?.title ??
    (pagePath ? pagePath.split("/").pop() ?? pagePath : t.wiki.overviewTitle);
  const generatedLabel = t.wiki.generated;
  const generatedAt = formatGeneratedAt(detail?.generated_at, locale);

  return (
    <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-gray-200 bg-white shadow-sm">
      <header className="border-b border-gray-100 px-5 py-4">
        <WikiBreadcrumbs repository={repository} path={pagePath} />
        <div className="mt-3 flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-sky-50 text-sky-600">
            <BookOpen size={20} aria-hidden />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-lg font-semibold tracking-tight text-gray-900">
              {title}
            </h2>
            <p className="mt-0.5 truncate font-mono text-xs text-gray-500">
              {pagePath || t.wiki.selectPage}
            </p>
            {generatedAt && (
              <p className="mt-1 text-xs text-gray-400">
                {generatedLabel}: <span className="font-mono text-gray-600">{generatedAt}</span>
              </p>
            )}
          </div>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-5 py-6">
        {isLoading && (
          <div className="animate-pulse space-y-3">
            <div className="h-4 w-2/3 rounded bg-gray-100" />
            <div className="h-4 w-full rounded bg-gray-100" />
            <div className="h-4 w-5/6 rounded bg-gray-100" />
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            {error.message}
          </div>
        )}

        {!isLoading && !error && detail && (
          <>
            <MarkdownRenderer content={detail.content} />

            {(detail.source_locations?.length ?? 0) > 0 && (
              <section className="mt-10 border-t border-gray-100 pt-8">
                <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-gray-900">
                  <FolderOpen size={16} aria-hidden />
                  {t.wiki.sourceLocations}
                </h3>
                <ul className="space-y-2 rounded-lg border border-gray-100 bg-gray-50/80 p-4">
                  {detail.source_locations.map((loc, i) => (
                    <SourceLocRow key={`${loc.file_path}-${loc.start_line}-${i}`} loc={loc} repository={repository} />
                  ))}
                </ul>
              </section>
            )}

            {detail && <CallChainSection repository={repository} detail={detail} />}
          </>
        )}

        {!isLoading && !error && !pagePath && (
          <p className="text-sm text-gray-600">{t.wiki.choosePageHint}</p>
        )}

        {!isLoading && !error && !detail && pagePath && (
          <p className="text-sm text-gray-500">{t.wiki.selectPageFromSidebar}</p>
        )}
      </div>
    </div>
  );
}
