import { ChevronRight, Home } from "lucide-react";
import { Link } from "react-router-dom";
import { useI18n } from "../../i18n/context";
import { wikiHref } from "./wikiRouteHelpers";

type Props = {
  repository: string;
  path: string;
  linkParams?: Record<string, string>;
  /** Maps path segment slugs to display titles (e.g. from topic tree). */
  titleMap?: Record<string, string>;
};

function segmentLabel(seg: string, titleMap?: Record<string, string>): string {
  const mapped = titleMap?.[seg]?.trim();
  if (mapped) return mapped;
  return decodeURIComponent(seg)
    .replace(/-/g, " ")
    .replace(/^_/, "")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function WikiBreadcrumbs({ repository, path, linkParams, titleMap }: Props) {
  const { t } = useI18n();
  const segments = path.split("/").filter(Boolean);

  return (
    <nav
      aria-label={t.common.breadcrumb}
      className="flex flex-wrap items-center gap-1 text-sm text-gray-600 dark:text-gray-400"
    >
      <Link
        to={wikiHref(undefined, linkParams)}
        className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium text-gray-700 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-gray-100"
      >
        <Home size={14} aria-hidden />
        {repository.trim() ? repository : t.wiki.title}
      </Link>
      {segments.map((seg, i) => {
        const to = wikiHref(segments.slice(0, i + 1).join("/"), linkParams);
        const label = segmentLabel(seg, titleMap);
        const last = i === segments.length - 1;
        return (
          <span key={to} className="inline-flex items-center gap-1">
            <ChevronRight size={14} className="text-gray-400 dark:text-gray-500" aria-hidden />
            {last ? (
              <span className="font-semibold text-gray-900 dark:text-gray-100">{label}</span>
            ) : (
              <Link
                to={to}
                className="rounded-md px-1.5 py-0.5 hover:bg-gray-100 hover:text-gray-900 dark:hover:bg-gray-800 dark:hover:text-gray-100"
              >
                {label}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}
