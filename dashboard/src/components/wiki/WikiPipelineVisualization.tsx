import { CheckCircle, Loader2, Circle, XCircle, ChevronRight } from "lucide-react";
import { useI18n } from "../../i18n/context";

export interface NodeStatus {
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  started_at?: number;
  completed_at?: number;
  elapsed_sec?: number;
  detail?: string;
  items_processed?: number;
  items_total?: number;
}

interface WikiPipelineVisualizationProps {
  nodeStatuses?: Record<string, NodeStatus>;
  currentPhase?: string;
  compact?: boolean;
}

const PIPELINE_NODES = [
  { key: "detect_reorg", phase: "detect_reorg", labelKey: "phaseDetectReorg" as const },
  { key: "classify_entity_roles", phase: "classify_entities", labelKey: "phaseClassifyEntityRoles" as const },
  { key: "graph_decompose", phase: "graph_decompose", labelKey: "phaseGraphDecompose" as const },
  { key: "assign_canonical_keys", phase: "assign_keys", labelKey: "phaseAssignKeys" as const },
  { key: "generate_titles", phase: "generate_titles", labelKey: "phaseGenerateTitles" as const },
  { key: "compose_leaf_modules", phase: "compose_leaf_modules", labelKey: "phaseComposeLeafModulesNew" as const },
  {
    key: "classify_architecture_layers",
    phase: "classify_architecture_layers",
    labelKey: "phaseClassifyArchitectureLayers" as const,
  },
  {
    key: "graph_domain_decompose",
    phase: "graph_domain_decompose",
    labelKey: "phaseGraphDomainDecompose" as const,
  },
  {
    key: "persist_classification",
    phase: "persist_classification",
    labelKey: "phasePersistClassification" as const,
  },
  { key: "set_review_status", phase: "set_review_status", labelKey: "phaseSetReviewStatus" as const },
  {
    key: "compose_domain_agents",
    phase: "compose_domain_agents",
    labelKey: "phaseComposeDomainAgents" as const,
  },
  { key: "summarize_leaves", phase: "summarize_leaves", labelKey: "phaseSummarizeLeaves" as const },
  {
    key: "compose_parent_pages",
    phase: "compose_parent_pages",
    labelKey: "phaseComposeParentPages" as const,
  },
  {
    key: "reassemble_domains",
    phase: "reassemble_domains",
    labelKey: "phaseReassembleDomains" as const,
  },
  {
    key: "compose_flow_agents",
    phase: "compose_flow_agents",
    labelKey: "phaseComposeFlowAgents" as const,
  },
  { key: "merge_flow_pages", phase: "merge_flow_pages", labelKey: "phaseMergeFlowPages" as const },
  { key: "quality_gate", phase: "quality_gate", labelKey: "phaseQualityGateNew" as const },
  { key: "heal_pages", phase: "heal_pages", labelKey: "phaseHealPages" as const },
  { key: "create_links", phase: "linking", labelKey: "phaseCreateLinks" as const },
  { key: "generate_tour", phase: "generate_tour", labelKey: "phaseGenerateTourNew" as const },
  { key: "finalize", phase: "finalize", labelKey: "phaseFinalizeNew" as const },
] as const;

function getNodeStatus(
  node: (typeof PIPELINE_NODES)[number],
  nodeStatuses?: Record<string, NodeStatus>,
  currentPhase?: string,
): { status: NodeStatus["status"]; detail?: string; elapsed?: number; progress?: string } {
  if (nodeStatuses) {
    // Try exact key first, then phase name
    const ns = nodeStatuses[node.key] ?? nodeStatuses[node.phase];
    if (ns) {
      return {
        status: ns.status,
        detail: ns.detail,
        elapsed: ns.elapsed_sec,
        progress:
          ns.items_processed != null && ns.items_total != null
            ? `${ns.items_processed}/${ns.items_total}`
            : undefined,
      };
    }
    // If no node_statuses data exists at all, fall back to currentPhase heuristic
    return { status: "pending" };
  }

  // Fallback: derive from currentPhase when no node_statuses are available
  if (!currentPhase) return { status: "pending" };

  const idx = PIPELINE_NODES.findIndex((n) => n.phase === currentPhase || n.key === currentPhase);
  const myIdx = PIPELINE_NODES.indexOf(node);

  if (idx < 0) return { status: "pending" };
  if (myIdx < idx) return { status: "completed" };
  if (myIdx === idx) return { status: "running" };
  return { status: "pending" };
}

function StatusIcon({ status }: { status: NodeStatus["status"] }) {
  switch (status) {
    case "completed":
      return <CheckCircle size={14} className="shrink-0 text-emerald-500 dark:text-emerald-400" />;
    case "running":
      return <Loader2 size={14} className="shrink-0 animate-spin text-sky-500 dark:text-sky-400" />;
    case "failed":
      return <XCircle size={14} className="shrink-0 text-red-500 dark:text-red-400" />;
    case "skipped":
      return <ChevronRight size={14} className="shrink-0 text-gray-400 dark:text-gray-500" />;
    default:
      return <Circle size={14} className="shrink-0 text-gray-300 dark:text-gray-600" />;
  }
}

export default function WikiPipelineVisualization({
  nodeStatuses,
  currentPhase,
  compact = false,
}: WikiPipelineVisualizationProps) {
  const { t } = useI18n();

  if (compact) {
    return (
      <div className="flex items-center gap-1" role="list" aria-label="Pipeline progress">
        {PIPELINE_NODES.map((node, idx) => {
          const { status } = getNodeStatus(node, nodeStatuses, currentPhase);
          const label = t.wiki[node.labelKey];
          return (
            <div key={node.key} className="flex items-center gap-0.5">
              <div
                role="listitem"
                aria-label={`${label}: ${status}`}
                className={`h-2 w-2 rounded-full transition-colors ${
                  status === "running"
                    ? "bg-sky-500 ring-2 ring-sky-300 dark:ring-sky-700"
                    : status === "completed"
                      ? "bg-emerald-400 dark:bg-emerald-500"
                      : status === "failed"
                        ? "bg-red-500"
                        : status === "skipped"
                          ? "bg-gray-300 dark:bg-gray-600"
                          : "bg-gray-200 dark:bg-gray-700"
                }`}
                title={label}
              />
              {idx < PIPELINE_NODES.length - 1 && (
                <div
                  className={`h-px w-1.5 ${
                    status === "completed"
                      ? "bg-emerald-400 dark:bg-emerald-500"
                      : "bg-gray-200 dark:bg-gray-700"
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <div className="space-y-0.5" role="list" aria-label="Pipeline nodes">
      {PIPELINE_NODES.map((node, idx) => {
        const { status, detail, elapsed, progress } = getNodeStatus(
          node,
          nodeStatuses,
          currentPhase,
        );
        const label = t.wiki[node.labelKey];
        const showTiming = (status === "completed" || status === "running") && elapsed != null;

        return (
          <div key={node.key} role="listitem" aria-label={`${label}: ${status}`} className="flex items-start gap-2">
            {/* Vertical connector line */}
            <div className="flex flex-col items-center">
              <StatusIcon status={status} />
              {idx < PIPELINE_NODES.length - 1 && (
                <div
                  className={`mt-0.5 h-4 w-px ${
                    status === "completed"
                      ? "bg-emerald-300 dark:bg-emerald-600"
                      : "bg-gray-200 dark:bg-gray-700"
                  }`}
                />
              )}
            </div>

            {/* Node info */}
            <div className="min-w-0 flex-1 pb-1">
              <div className="flex items-center gap-2">
                <span
                  className={`text-xs font-medium ${
                    status === "running"
                      ? "text-sky-700 dark:text-sky-300"
                      : status === "completed"
                        ? "text-gray-600 dark:text-gray-400"
                        : status === "failed"
                          ? "text-red-600 dark:text-red-400"
                          : "text-gray-400 dark:text-gray-500"
                  }`}
                >
                  {label}
                </span>
                {showTiming && (
                  <span className="text-[10px] text-gray-400 dark:text-gray-500">
                    {t.wiki.nodeElapsed.replace("{elapsed}", String(elapsed.toFixed(1)))}
                  </span>
                )}
                {progress && (
                  <span className="text-[10px] text-sky-500 dark:text-sky-400">{progress}</span>
                )}
              </div>
              {detail && status === "running" && (
                <p className="mt-0.5 truncate text-[10px] text-gray-400 dark:text-gray-500">
                  {detail}
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
