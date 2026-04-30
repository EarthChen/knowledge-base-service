import { CheckCircle, AlertTriangle, RefreshCw, Layers } from "lucide-react";

interface DomainNode {
  name: string;
  description?: string;
  modules: string[];
  children: DomainNode[];
}

interface Props {
  domainTree: DomainNode[];
  reviewStatus: Record<string, string>;
  onApprove: () => void;
  onRegenerate: (domainNames: string[]) => void;
}

export default function WikiDomainReviewPanel({
  domainTree,
  reviewStatus,
  onApprove,
  onRegenerate,
}: Props) {
  const isPending = reviewStatus.domain_tree === "pending_review";

  return (
    <div className="space-y-4">
      {isPending && (
        <div className="flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
          <AlertTriangle size={16} />
          <span>域树待审阅 — 请检查域划分是否合理，确认后点击"批准"</span>
          <button
            type="button"
            onClick={onApprove}
            className="ml-auto flex items-center gap-1 rounded-md bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-500"
          >
            <CheckCircle size={12} /> 批准
          </button>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {domainTree.map((domain) => (
          <div key={domain.name} className="rounded-xl border border-gray-200 p-4 dark:border-gray-700">
            <div className="flex items-center gap-2">
              <Layers size={16} className="text-sky-600 dark:text-sky-400" />
              <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">{domain.name}</h3>
            </div>
            {domain.description && (
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{domain.description}</p>
            )}
            <div className="mt-2 text-xs text-gray-400 dark:text-gray-500">
              {domain.modules.length} modules
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              {domain.modules.slice(0, 5).map((m) => (
                <span
                  key={m}
                  className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600 dark:bg-gray-800 dark:text-gray-400"
                >
                  {m}
                </span>
              ))}
              {domain.modules.length > 5 && (
                <span className="text-[10px] text-gray-400">+{domain.modules.length - 5}</span>
              )}
            </div>
            {isPending && (
              <button
                type="button"
                onClick={() => onRegenerate([domain.name])}
                className="mt-3 flex items-center gap-1 text-xs text-sky-600 hover:text-sky-500 dark:text-sky-400"
              >
                <RefreshCw size={12} /> 重新生成此域
              </button>
            )}
            {domain.children.length > 0 && (
              <div className="mt-2 border-t border-gray-100 pt-2 dark:border-gray-800">
                <div className="text-[10px] font-medium text-gray-400">子域:</div>
                {domain.children.map((child) => (
                  <div key={child.name} className="ml-2 text-[11px] text-gray-500 dark:text-gray-400">
                    └ {child.name} ({child.modules.length} modules)
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
