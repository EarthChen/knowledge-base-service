import { ArrowDown, ArrowRight, ArrowUp, GitBranch } from "lucide-react";
import { Link } from "react-router-dom";
import { useWikiNavigation } from "../../hooks/useWikiNavigation";
import { useI18n } from "../../i18n/context";
import { wikiHref } from "./wikiRouteHelpers";

type Props = {
  repository: string;
  pagePath: string;
  wikiLinkParams?: Record<string, string>;
};

function pageLabel(p: string): string {
  return p.split("/").pop()?.replace(".md", "") ?? p;
}

export default function WikiNavigationLinks({ repository, pagePath, wikiLinkParams }: Props) {
  const { t } = useI18n();
  const { data: nav, isLoading, isError } = useWikiNavigation(repository, pagePath);

  if (isLoading || !nav) return null;
  if (isError) return null;

  const siblingPaths = nav.sibling_paths ?? [];
  const childPaths = nav.child_paths ?? [];
  const relatedFlowPaths = nav.related_flow_paths ?? [];
  const hasAnyLinks =
    nav.parent_path ||
    siblingPaths.length > 0 ||
    childPaths.length > 0 ||
    relatedFlowPaths.length > 0;
  if (!hasAnyLinks) return null;

  const params = wikiLinkParams ?? { business_id: repository };

  return (
    <div className="mt-4 space-y-3 rounded-lg border border-gray-200 bg-gray-50/50 p-3 dark:border-gray-700 dark:bg-gray-800/30">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
        {t.wiki.navHeading}
      </h4>
      {nav.parent_path && (
        <div className="flex items-center gap-2 text-sm">
          <ArrowUp size={14} className="shrink-0 text-gray-400" />
          <span className="text-gray-500">{t.wiki.navParent}</span>
          <Link
            to={wikiHref(nav.parent_path, params)}
            className="truncate text-blue-600 hover:underline dark:text-blue-400"
          >
            {nav.parent_title || nav.parent_path}
          </Link>
        </div>
      )}
      {childPaths.length > 0 && (
        <div className="text-sm">
          <div className="flex items-center gap-2 text-gray-500">
            <ArrowDown size={14} className="shrink-0" />
            <span>{t.wiki.navChildren.replace("{count}", String(childPaths.length))}</span>
          </div>
          <ul className="ml-6 mt-1 space-y-0.5">
            {childPaths.slice(0, 10).map((p) => (
              <li key={p}>
                <Link
                  to={wikiHref(p, params)}
                  className="text-sm text-blue-600 hover:underline dark:text-blue-400"
                >
                  {pageLabel(p)}
                </Link>
              </li>
            ))}
            {childPaths.length > 10 && (
              <li className="text-xs text-gray-400">
                {t.wiki.navMore.replace("{count}", String(childPaths.length - 10))}
              </li>
            )}
          </ul>
        </div>
      )}
      {siblingPaths.length > 0 && (
        <div className="text-sm">
          <div className="flex items-center gap-2 text-gray-500">
            <ArrowRight size={14} className="shrink-0" />
            <span>{t.wiki.navSiblings.replace("{count}", String(siblingPaths.length))}</span>
          </div>
          <ul className="ml-6 mt-1 space-y-0.5">
            {siblingPaths.slice(0, 8).map((p) => (
              <li key={p}>
                <Link
                  to={wikiHref(p, params)}
                  className="text-sm text-blue-600 hover:underline dark:text-blue-400"
                >
                  {pageLabel(p)}
                </Link>
              </li>
            ))}
            {siblingPaths.length > 8 && (
              <li className="text-xs text-gray-400">
                {t.wiki.navMore.replace("{count}", String(siblingPaths.length - 8))}
              </li>
            )}
          </ul>
        </div>
      )}
      {relatedFlowPaths.length > 0 && (
        <div className="text-sm">
          <div className="flex items-center gap-2 text-gray-500">
            <GitBranch size={14} className="shrink-0" />
            <span>{t.wiki.navBusinessFlows}</span>
          </div>
          <ul className="ml-6 mt-1 space-y-0.5">
            {relatedFlowPaths.map((p) => (
              <li key={p}>
                <Link
                  to={wikiHref(p, params)}
                  className="text-sm text-blue-600 hover:underline dark:text-blue-400"
                >
                  {pageLabel(p).replace("business-flow-", "Flow ")}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
