import { useMemo, useState } from "react";
import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  Database,
  Layers,
  Server,
  Wrench,
} from "lucide-react";
import { useWikiTour } from "../../hooks/useWikiTour";

interface WikiGuidedTourProps {
  businessId: string;
  currentPath: string;
  onNavigate?: (path: string) => void;
}

function layerIcon(layerName: string) {
  switch (layerName) {
    case "api":
      return BookOpen;
    case "service":
      return Layers;
    case "data":
      return Database;
    case "infrastructure":
      return Server;
    default:
      return Wrench;
  }
}

function TourLoadingSkeleton() {
  return (
    <div data-testid="tour-loading" className="space-y-3 p-4">
      <div className="h-2 w-full animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
      {[1, 2, 3].map((i) => (
        <div key={i} className="space-y-2">
          <div className="h-5 w-2/3 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
          <div className="ml-4 h-4 w-full animate-pulse rounded bg-gray-100 dark:bg-gray-800" />
          <div className="ml-4 h-4 w-5/6 animate-pulse rounded bg-gray-100 dark:bg-gray-800" />
        </div>
      ))}
    </div>
  );
}

export default function WikiGuidedTour({
  businessId,
  currentPath,
  onNavigate,
}: WikiGuidedTourProps) {
  const { data, isLoading } = useWikiTour(businessId);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const currentReadingOrder = useMemo(() => {
    if (!data?.steps || !currentPath) return 0;
    for (const step of data.steps) {
      for (const page of step.pages) {
        if (page.path === currentPath) return page.reading_order;
      }
    }
    return 0;
  }, [data, currentPath]);

  const pagesRead = useMemo(() => {
    if (!data?.steps || currentReadingOrder <= 0) return 0;
    let count = 0;
    for (const step of data.steps) {
      for (const page of step.pages) {
        if (page.reading_order <= currentReadingOrder) count += 1;
      }
    }
    return count;
  }, [data, currentReadingOrder]);

  const totalPages = data?.total_pages ?? 0;
  const progressPct = totalPages > 0 ? Math.round((pagesRead / totalPages) * 100) : 0;

  const toggleLayer = (layerName: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(layerName)) next.delete(layerName);
      else next.add(layerName);
      return next;
    });
  };

  if (isLoading) return <TourLoadingSkeleton />;

  if (!data?.steps?.length) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 p-6 text-center text-sm text-gray-500 dark:text-gray-400">
        <BookOpen className="h-8 w-8 opacity-40" />
        <p>No guided tour available</p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-gray-200 px-4 py-3 dark:border-gray-700">
        <div className="mb-1 flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
          <span>Reading progress</span>
          <span>
            {pagesRead} / {totalPages}
          </span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
          <div
            className="h-full rounded-full bg-blue-500 transition-all duration-300"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {data.steps.map((step) => {
          const Icon = layerIcon(step.layer_name);
          const isCollapsed = collapsed.has(step.layer_name);

          return (
            <div key={step.layer_name} className="mb-1">
              <button
                type="button"
                onClick={() => toggleLayer(step.layer_name)}
                className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm font-medium text-gray-700 hover:bg-gray-50 dark:text-gray-200 dark:hover:bg-gray-800"
              >
                {isCollapsed ? (
                  <ChevronRight className="h-4 w-4 shrink-0 text-gray-400" />
                ) : (
                  <ChevronDown className="h-4 w-4 shrink-0 text-gray-400" />
                )}
                <Icon className="h-4 w-4 shrink-0 text-blue-500" />
                <span className="flex-1 truncate">{step.layer_display}</span>
                <span className="text-xs text-gray-400">{step.pages.length}</span>
              </button>

              {!isCollapsed && (
                <ul className="ml-2 space-y-0.5 pb-2 pl-4">
                  {step.pages.map((page) => {
                    const isCurrent = page.path === currentPath;
                    return (
                      <li key={page.path}>
                        <button
                          type="button"
                          data-current={isCurrent ? "true" : "false"}
                          onClick={() => onNavigate?.(page.path)}
                          className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors ${
                            isCurrent
                              ? "bg-blue-100 font-medium text-blue-800 dark:bg-blue-900/40 dark:text-blue-200"
                              : "text-gray-600 hover:bg-gray-50 dark:text-gray-300 dark:hover:bg-gray-800"
                          }`}
                        >
                          <span
                            className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
                              isCurrent
                                ? "bg-blue-500 text-white"
                                : "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400"
                            }`}
                          >
                            {page.reading_order}
                          </span>
                          <span className="truncate">{page.title}</span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
