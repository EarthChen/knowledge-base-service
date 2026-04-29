import { Link } from "react-router-dom";
import { explorerGraphHref } from "../../routes/explorerRouteHelpers";

export interface RelatedPageInfo {
  uid: string;
  title: string;
  page_type: string;
  business_domain: string | null;
}

interface RelatedPagesProps {
  pages: RelatedPageInfo[];
}

/** See-also / graph neighbors (RELATED_TO) with links into the graph explorer. */
export function RelatedPages({ pages }: RelatedPagesProps) {
  if (!pages.length) return null;

  return (
    <aside className="mt-8 rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-800/50">
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
        See Also
      </h3>
      <ul className="space-y-2">
        {pages.map((p) => (
          <li key={p.uid}>
            <Link
              to={explorerGraphHref(p.uid)}
              className="group flex items-center gap-2 text-sm text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300"
            >
              <span className="truncate">{p.title}</span>
              {p.business_domain && (
                <span className="shrink-0 rounded-full bg-blue-100 px-2 py-0.5 text-xs text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
                  {p.business_domain}
                </span>
              )}
            </Link>
          </li>
        ))}
      </ul>
    </aside>
  );
}
