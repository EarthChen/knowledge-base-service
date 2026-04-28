import { ArrowDown, ArrowRight, ArrowUp, GitBranch } from "lucide-react";
import { Link } from "react-router-dom";
import { useWikiNavigation } from "../../hooks/useWikiNavigation";
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
  const { data: nav, isLoading } = useWikiNavigation(repository, pagePath);

  if (isLoading || !nav) return null;

  const hasAnyLinks =
    nav.parent_path ||
    nav.sibling_paths.length > 0 ||
    nav.child_paths.length > 0 ||
    nav.related_flow_paths.length > 0;
  if (!hasAnyLinks) return null;

  const params = wikiLinkParams ?? { business_id: repository };

  return (
    <div className="mt-4 space-y-3 rounded-lg border border-gray-200 bg-gray-50/50 p-3 dark:border-gray-700 dark:bg-gray-800/30">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
        Navigation
      </h4>
      {nav.parent_path && (
        <div className="flex items-center gap-2 text-sm">
          <ArrowUp size={14} className="shrink-0 text-gray-400" />
          <span className="text-gray-500">Parent:</span>
          <Link
            to={wikiHref(nav.parent_path, params)}
            className="truncate text-blue-600 hover:underline dark:text-blue-400"
          >
            {nav.parent_title || nav.parent_path}
          </Link>
        </div>
      )}
      {nav.child_paths.length > 0 && (
        <div className="text-sm">
          <div className="flex items-center gap-2 text-gray-500">
            <ArrowDown size={14} className="shrink-0" />
            <span>Children ({nav.child_paths.length}):</span>
          </div>
          <ul className="ml-6 mt-1 space-y-0.5">
            {nav.child_paths.slice(0, 10).map((p) => (
              <li key={p}>
                <Link
                  to={wikiHref(p, params)}
                  className="text-sm text-blue-600 hover:underline dark:text-blue-400"
                >
                  {pageLabel(p)}
                </Link>
              </li>
            ))}
            {nav.child_paths.length > 10 && (
              <li className="text-xs text-gray-400">+{nav.child_paths.length - 10} more</li>
            )}
          </ul>
        </div>
      )}
      {nav.sibling_paths.length > 0 && (
        <div className="text-sm">
          <div className="flex items-center gap-2 text-gray-500">
            <ArrowRight size={14} className="shrink-0" />
            <span>Siblings ({nav.sibling_paths.length}):</span>
          </div>
          <ul className="ml-6 mt-1 space-y-0.5">
            {nav.sibling_paths.slice(0, 8).map((p) => (
              <li key={p}>
                <Link
                  to={wikiHref(p, params)}
                  className="text-sm text-blue-600 hover:underline dark:text-blue-400"
                >
                  {pageLabel(p)}
                </Link>
              </li>
            ))}
            {nav.sibling_paths.length > 8 && (
              <li className="text-xs text-gray-400">+{nav.sibling_paths.length - 8} more</li>
            )}
          </ul>
        </div>
      )}
      {nav.related_flow_paths.length > 0 && (
        <div className="text-sm">
          <div className="flex items-center gap-2 text-gray-500">
            <GitBranch size={14} className="shrink-0" />
            <span>Business Flows:</span>
          </div>
          <ul className="ml-6 mt-1 space-y-0.5">
            {nav.related_flow_paths.map((p) => (
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
