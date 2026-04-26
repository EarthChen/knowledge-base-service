import { useCallback, useRef, useState, type ReactNode } from "react";
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
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const bid = businessId.trim() || "default";
  const { data, isLoading } = useWikiPageByPath(bid, path);

  const handleMouseEnter = useCallback(() => {
    timerRef.current = setTimeout(() => setShow(true), 300);
  }, []);

  const handleMouseLeave = useCallback(() => {
    clearTimeout(timerRef.current);
    setShow(false);
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
    <span className="relative inline" onMouseEnter={handleMouseEnter} onMouseLeave={handleMouseLeave}>
      <a
        href={wikiHref(path, wikiLinkParams)}
        onClick={handleClick}
        className="font-medium text-sky-700 underline decoration-sky-300/50 decoration-1 underline-offset-2 transition-colors hover:text-sky-900 hover:decoration-sky-400 dark:text-sky-400 dark:decoration-sky-700 dark:hover:text-sky-300"
      >
        {children}
      </a>
      {show && (
        <span
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
              </span>
              {snippet && (
                <span className="mt-2 block text-xs leading-relaxed text-gray-600 dark:text-gray-400">
                  {snippet}...
                </span>
              )}
              <span className="mt-2 block truncate font-mono text-[10px] text-gray-400">{path}</span>
            </>
          ) : (
            <span className="text-xs text-gray-500 dark:text-gray-400">{t.wiki.linkPreviewNotGenerated}</span>
          )}
        </span>
      )}
    </span>
  );
}
