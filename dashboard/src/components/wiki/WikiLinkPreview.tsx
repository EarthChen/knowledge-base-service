import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { FileText, Loader2 } from "lucide-react";
import { useWikiPageByPath } from "../../hooks/useWikiPageByPath";
import { wikiHref } from "./wikiRouteHelpers";
import { useI18n } from "../../i18n/context";

interface WikiLinkPreviewProps {
  path: string;
  businessId: string;
  wikiLinkParams?: Record<string, string>;
  children: ReactNode;
}

export default function WikiLinkPreview({ path, businessId, wikiLinkParams, children }: WikiLinkPreviewProps) {
  const navigate = useNavigate();
  const { t } = useI18n();
  const [show, setShow] = useState(false);
  const previewId = useId();
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const bid = businessId.trim() || "default";
  const [shouldFetch, setShouldFetch] = useState(false);
  const { data, isLoading } = useWikiPageByPath(bid, path, { enabled: shouldFetch });

  useEffect(() => () => clearTimeout(timerRef.current), []);

  const handleMouseEnter = useCallback(() => {
    timerRef.current = setTimeout(() => {
      setShouldFetch(true);
      setShow(true);
    }, 300);
  }, []);

  const handleMouseLeave = useCallback(() => {
    clearTimeout(timerRef.current);
    setShow(false);
    setShouldFetch(false);
  }, []);

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      navigate(wikiHref(path, wikiLinkParams));
    },
    [navigate, path, wikiLinkParams],
  );

  const snippet = data?.content?.slice(0, 200)?.replace(/^#+\s.+\n/, "") || "";

  return (
    <span
      className="relative inline"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <a
        href={wikiHref(path, wikiLinkParams)}
        onClick={handleClick}
        onFocus={handleMouseEnter}
        onBlur={handleMouseLeave}
        aria-describedby={show ? previewId : undefined}
        className="font-medium text-sky-700 underline decoration-sky-300/50 decoration-1 underline-offset-2 transition-colors hover:text-sky-900 hover:decoration-sky-400 dark:text-sky-400 dark:decoration-sky-700 dark:hover:text-sky-300"
      >
        {children}
      </a>
      {show && (
        <span
          id={previewId}
          role="tooltip"
          className="absolute bottom-full left-1/2 z-50 mb-2 w-72 -translate-x-1/2 rounded-xl border border-gray-200 bg-white p-4 shadow-lg dark:border-gray-700 dark:bg-gray-900"
          onMouseEnter={() => clearTimeout(timerRef.current)}
          onMouseLeave={handleMouseLeave}
        >
          {isLoading ? (
            <span className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 size={14} className="animate-spin" />
              {t.common.loading}
            </span>
          ) : data ? (
            <>
              <span className="flex items-center gap-2">
                <FileText size={14} className="shrink-0 text-sky-500" />
                <span className="truncate text-sm font-semibold text-gray-900 dark:text-gray-100">
                  {data.title}
                </span>
                {data.context?.importance_tier && (
                  <span className={`shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase ${
                    data.context.importance_tier === "core"
                      ? "bg-sky-100 text-sky-700 dark:bg-sky-900/50 dark:text-sky-300"
                      : data.context.importance_tier === "standard"
                        ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300"
                        : "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400"
                  }`}>
                    {data.context.importance_tier}
                  </span>
                )}
              </span>
              {snippet && (
                <span className="mt-2 block text-xs leading-relaxed text-gray-600 dark:text-gray-400">
                  {snippet}...
                </span>
              )}
              <span className="mt-1.5 flex items-center gap-1.5">
                {data.context?.repository && (
                  <span className="truncate text-[10px] text-gray-500 dark:text-gray-400">
                    {data.context.repository}
                  </span>
                )}
                <span className="truncate font-mono text-[10px] text-gray-400">{path}</span>
              </span>
            </>
          ) : (
            <span className="text-xs text-gray-500 dark:text-gray-400">{t.wiki.linkPreviewNotGenerated}</span>
          )}
        </span>
      )}
    </span>
  );
}
