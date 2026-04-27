import { useMemo } from "react";
import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { useWikiTree } from "../../hooks/useWikiTree";
import { useI18n } from "../../i18n/context";
import WikiCoverageCard from "./WikiCoverageCard";
import { wikiHref } from "./wikiRouteHelpers";
import { getErrorMessage } from "../../utils/errorUtils";

type ViewType = "business_domain" | "code_structure";

type WikiTier = "standard" | "essential" | "comprehensive" | null;

type Props = {
  businessId: string;
  viewType: ViewType;
  wikiTier: WikiTier;
};

export default function WikiLandingPage({ businessId, viewType, wikiTier }: Props) {
  const { t } = useI18n();
  const treeQuery = useWikiTree(businessId, viewType, wikiTier);
  const roots = treeQuery.data?.tree ?? [];

  const linkParams = useMemo(
    () =>
      ({
        business_id: businessId,
        view: viewType,
        ...(wikiTier ? { wiki_tier: wikiTier } : {}),
      }) as Record<string, string>,
    [businessId, viewType, wikiTier],
  );

  return (
    <div className="space-y-6">
      <WikiCoverageCard businessId={businessId} />

      <div>
        <h3 className="mb-3 text-sm font-semibold text-gray-900 dark:text-gray-100">
          {t.wiki.domainsHeading}
        </h3>
        {treeQuery.isLoading && (
          <p className="text-sm text-gray-500 dark:text-gray-400">{t.wiki.loadingPages}</p>
        )}
        {treeQuery.isError && (
          <p className="text-sm text-red-600 dark:text-red-400">
            {getErrorMessage(treeQuery.error, t.common.unexpectedError)}
          </p>
        )}
        {!treeQuery.isLoading && !treeQuery.isError && roots.length === 0 && (
          <p className="text-sm text-gray-500 dark:text-gray-400">{t.wiki.noPagesFound}</p>
        )}
        {roots.length > 0 && (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {roots.map((node) => {
              const subCount = node.children?.length ?? 0;
              const href = node.path
                ? wikiHref(node.path, linkParams)
                : wikiHref(undefined, linkParams);
              return (
                <li key={node.uid}>
                  <Link
                    to={href}
                    className="flex h-full flex-col justify-between rounded-xl border border-gray-200 bg-white p-4 shadow-sm transition-colors hover:border-sky-200 hover:bg-sky-50/40 dark:border-gray-700 dark:bg-gray-900 dark:hover:border-sky-800 dark:hover:bg-sky-950/30"
                  >
                    <div className="min-w-0">
                      <div className="font-medium text-gray-900 dark:text-gray-100">
                        {node.title || node.label}
                      </div>
                      {subCount > 0 ? (
                        <div className="mt-1 text-xs tabular-nums text-gray-500 dark:text-gray-400">
                          {subCount}
                        </div>
                      ) : null}
                    </div>
                    <div className="mt-3 flex justify-end text-sky-600 dark:text-sky-400">
                      <ChevronRight size={18} aria-hidden />
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
