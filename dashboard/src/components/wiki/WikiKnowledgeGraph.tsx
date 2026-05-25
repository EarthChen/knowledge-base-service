/* eslint-disable react-refresh/only-export-components -- primaryLayer/layoutWithDagre exported for unit tests */
import { useMemo, useCallback, useState, useEffect } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeMouseHandler,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useI18n } from "../../i18n/context";

function useDarkMode(): boolean {
  const [isDark, setIsDark] = useState(() =>
    document.documentElement.classList.contains("dark"),
  );
  useEffect(() => {
    const el = document.documentElement;
    const observer = new MutationObserver(() => {
      setIsDark(el.classList.contains("dark"));
    });
    observer.observe(el, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);
  return isDark;
}

interface LayerStyle {
  bg: string;
  border: string;
  text: string;
}

const LAYER_COLORS: Record<string, { light: LayerStyle; dark: LayerStyle }> = {
  api: {
    light: { bg: "#dbeafe", border: "#3b82f6", text: "#1e40af" },
    dark: { bg: "#1e3a5f", border: "#60a5fa", text: "#93c5fd" },
  },
  service: {
    light: { bg: "#fef3c7", border: "#f59e0b", text: "#92400e" },
    dark: { bg: "#451a03", border: "#fbbf24", text: "#fde68a" },
  },
  data: {
    light: { bg: "#d1fae5", border: "#10b981", text: "#065f46" },
    dark: { bg: "#064e3b", border: "#34d399", text: "#6ee7b7" },
  },
  infrastructure: {
    light: { bg: "#ede9fe", border: "#8b5cf6", text: "#5b21b6" },
    dark: { bg: "#2e1065", border: "#a78bfa", text: "#c4b5fd" },
  },
  unknown: {
    light: { bg: "#f1f5f9", border: "#94a3b8", text: "#475569" },
    dark: { bg: "#1e293b", border: "#475569", text: "#e2e8f0" },
  },
};

export function primaryLayer(layers: Record<string, number>): string {
  const entries = Object.entries(layers);
  if (entries.length === 0) return "unknown";
  return entries.sort(([, a], [, b]) => b - a)[0][0];
}

export function layoutWithDagre(
  nodes: Node[],
  edges: Edge[],
  direction: "TB" | "LR" = "TB",
): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: direction, nodesep: 60, ranksep: 80 });

  for (const n of nodes) {
    g.setNode(n.id, { width: 200, height: 80 });
  }
  for (const e of edges) {
    g.setEdge(e.source, e.target);
  }

  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    return {
      ...n,
      position: { x: pos.x - 100, y: pos.y - 40 },
    };
  });
}

interface DomainNodeData {
  label: string;
  moduleCount: number;
  architectureLayers: Record<string, number>;
  hasChildren: boolean;
  isExpanded: boolean;
  colors: LayerStyle;
}

function DomainNode({ data }: NodeProps) {
  const nodeData = data as unknown as DomainNodeData;
  return (
    <div
      style={{
        position: "relative",
        background: nodeData.colors.bg,
        border: `2px solid ${nodeData.colors.border}`,
        borderRadius: "8px",
        padding: "10px 14px",
        minWidth: "160px",
        cursor: "pointer",
      }}
    >
      <Handle type="target" position={Position.Top} style={{ visibility: "hidden" }} />
      <div style={{ fontWeight: 600, fontSize: "12px", color: nodeData.colors.text }}>
        {nodeData.label}
      </div>
      <div style={{ fontSize: "11px", opacity: 0.7, color: nodeData.colors.text, marginTop: 2 }}>
        {nodeData.moduleCount} modules
      </div>
      {nodeData.hasChildren && (
        <div style={{ position: "absolute", right: 6, top: 6 }}>
          {nodeData.isExpanded ? (
            <ChevronDown size={14} style={{ color: nodeData.colors.text }} />
          ) : (
            <ChevronRight size={14} style={{ color: nodeData.colors.text }} />
          )}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} style={{ visibility: "hidden" }} />
    </div>
  );
}

interface DomainInfo {
  id: string;
  label: string;
  children: string[];
  moduleCount?: number;
  architectureLayers?: Record<string, number>;
}

interface DomainEdge {
  source: string;
  target: string;
  label: string;
}

interface Props {
  domains: DomainInfo[];
  domainEdges: DomainEdge[];
  onNodeClick: (domainId: string) => void;
  /** When true, shows loading UI (e.g. parent React Query initial fetch). */
  isLoading?: boolean;
  /** When set, shows error UI instead of the graph. */
  error?: unknown;
}

export default function WikiKnowledgeGraph({
  domains,
  domainEdges,
  onNodeClick,
  isLoading = false,
  error = null,
}: Props) {
  const { t } = useI18n();
  const kg = t.wiki.knowledge_graph;
  const isDark = useDarkMode();
  const [expandedDomains, setExpandedDomains] = useState<Set<string>>(new Set());

  const parentIdMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const d of domains) {
      for (const childId of d.children) {
        map.set(childId, d.id);
      }
    }
    return map;
  }, [domains]);

  const visibleDomains = useMemo(() => {
    const result: DomainInfo[] = [];
    for (const d of domains) {
      const parentId = parentIdMap.get(d.id);
      if (!parentId) {
        result.push(d);
      } else if (expandedDomains.has(parentId)) {
        result.push(d);
      }
    }
    return result;
  }, [domains, expandedDomains, parentIdMap]);

  const aggregatedLayers = useMemo(() => {
    const result = new Map<string, Record<string, number>>();
    for (const d of domains) {
      if (d.children.length > 0) {
        const agg: Record<string, number> = {};
        for (const childId of d.children) {
          const child = domains.find((c) => c.id === childId);
          for (const [layer, count] of Object.entries(child?.architectureLayers ?? {})) {
            agg[layer] = (agg[layer] ?? 0) + count;
          }
        }
        result.set(d.id, agg);
      }
    }
    return result;
  }, [domains]);

  const filteredEdges: Edge[] = useMemo(() => {
    const visibleIds = new Set(visibleDomains.map((d) => d.id));
    return domainEdges
      .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
      .map((e, i) => ({
        id: `edge-${i}`,
        source: e.source,
        target: e.target,
        label: e.label,
        animated: true,
        style: { stroke: "#94a3b8" },
        labelStyle: { fontSize: 10, fill: "#64748b" },
      }));
  }, [domainEdges, visibleDomains]);

  const nodes: Node[] = useMemo(() => {
    const rawNodes: Node[] = visibleDomains.map((d) => {
      const layers = aggregatedLayers.get(d.id) ?? d.architectureLayers ?? {};
      const primary = primaryLayer(layers);
      const colors =
        LAYER_COLORS[primary]?.[isDark ? "dark" : "light"] ??
        LAYER_COLORS.unknown[isDark ? "dark" : "light"];
      const hasChildren = d.children.length > 0;
      const isExpanded = expandedDomains.has(d.id);

      return {
        id: d.id,
        position: { x: 0, y: 0 },
        type: "domainNode",
        data: {
          label: d.label,
          moduleCount: d.moduleCount ?? d.children.length,
          architectureLayers: layers,
          hasChildren,
          isExpanded,
          colors,
        },
      };
    });

    return layoutWithDagre(rawNodes, filteredEdges);
  }, [visibleDomains, aggregatedLayers, isDark, expandedDomains, filteredEdges]);

  const nodeTypes = useMemo(() => ({ domainNode: DomainNode }), []);

  const handleNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      const domain = domains.find((d) => d.id === node.id);
      if (domain && domain.children.length > 0) {
        setExpandedDomains((prev) => {
          const next = new Set(prev);
          if (next.has(node.id)) {
            next.delete(node.id);
          } else {
            next.add(node.id);
          }
          return next;
        });
      }
      onNodeClick(node.id);
    },
    [domains, onNodeClick],
  );

  if (isLoading) {
    return (
      <div className="flex h-48 items-center justify-center text-sm text-gray-400 dark:text-gray-500">
        {kg.loading}
      </div>
    );
  }
  if (error != null) {
    const message = error instanceof Error ? error.message : String(error);
    return (
      <div className="flex h-48 items-center justify-center text-sm text-red-400 dark:text-red-400">
        {kg.load_failed}: {message}
      </div>
    );
  }

  if (domains.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center rounded-lg border border-gray-200 text-sm text-gray-400 dark:border-gray-700">
        {kg.no_data}
      </div>
    );
  }

  return (
    <div className="h-[500px] w-full rounded-lg border border-gray-200 dark:border-gray-700">
      <ReactFlow
        nodes={nodes}
        edges={filteredEdges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </div>
  );
}
