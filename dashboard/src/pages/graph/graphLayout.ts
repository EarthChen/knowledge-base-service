import dagre from "@dagrejs/dagre";
import { MarkerType, type Edge, type Node } from "@xyflow/react";
import type { GraphEdge as ApiEdge, GraphNode as ApiNode } from "../../api/types";

export type NodeTypeKey = "Function" | "Class" | "Module" | "Document";

export const TYPE_FLOW_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  Function: { bg: "#ecfdf5", border: "#10b981", text: "#065f46" },
  Class: { bg: "#f0f9ff", border: "#0ea5e9", text: "#0c4a6e" },
  Module: { bg: "#faf5ff", border: "#a855f7", text: "#581c87" },
  Document: { bg: "#fffbeb", border: "#fbbf24", text: "#92400e" },
  Unknown: { bg: "#f1f5f9", border: "#64748b", text: "#334155" },
};

export const TYPE_FLOW_COLORS_DARK: Record<string, { bg: string; border: string; text: string }> = {
  Function: { bg: "#064e3c", border: "#34d399", text: "#d1fae5" },
  Class: { bg: "#0c4a6e", border: "#38bdf8", text: "#e0f2fe" },
  Module: { bg: "#581c87", border: "#c084fc", text: "#f3e8ff" },
  Document: { bg: "#78350f", border: "#fbbf24", text: "#fef3c7" },
  Unknown: { bg: "#1e293b", border: "#94a3b8", text: "#e2e8f0" },
};

export const EDGE_COLORS: Record<string, string> = {
  CALLS: "#10b981",
  INHERITS: "#0ea5e9",
  IMPORTS: "#a855f7",
  CONTAINS: "#fbbf24",
  REFERENCES: "#ef4444",
  USES_TYPE: "#ec4899",
};

export const DEFAULT_VISIBILITY: Record<NodeTypeKey, boolean> = {
  Function: true,
  Class: true,
  Module: true,
  Document: true,
};

/** Initial paint cap for POST /graph/explore results (progressive expansion adds more). */
export const INITIAL_NODE_LIMIT = 50;
/** Hard safety cap to prevent browser tab from exhausting memory. */
export const MAX_GRAPH_NODES = 500;
const NODE_WIDTH = 160;
const NODE_HEIGHT = 48;

export const INPUT_CLASS =
  "rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-300 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 dark:placeholder-gray-500 dark:focus:border-sky-500 dark:focus:ring-sky-700";

export const CHIP_BASE =
  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors dark:border-gray-600";

export function paletteForTheme(isDark: boolean) {
  return isDark ? TYPE_FLOW_COLORS_DARK : TYPE_FLOW_COLORS;
}

export function mergeGraphEdges(existing: ApiEdge[], incoming: ApiEdge[]): ApiEdge[] {
  const key = (e: ApiEdge) => `${e.source}|${e.type}|${e.target}`;
  const out = new Map<string, ApiEdge>();
  for (const e of existing) out.set(key(e), e);
  for (const e of incoming) out.set(key(e), e);
  return [...out.values()];
}

export function normalizeGraphType(raw: string): keyof typeof TYPE_FLOW_COLORS {
  const t = raw?.trim();
  if (t === "Function" || t === "Class" || t === "Module" || t === "Document") return t;
  return "Unknown";
}

function hasInheritsEdges(apiEdges: ApiEdge[]): boolean {
  return apiEdges.some((e) => e.type === "INHERITS");
}

export function depthRowClass(depth: number, maxDepth: number): string {
  if (maxDepth <= 1) {
    return "bg-amber-500/25 dark:bg-amber-400/30";
  }
  const step = (depth - 1) / Math.max(maxDepth - 1, 1);
  if (step <= 0.34) return "bg-amber-500/30 dark:bg-amber-400/35";
  if (step <= 0.67) return "bg-amber-500/18 dark:bg-amber-400/22";
  return "bg-amber-500/10 dark:bg-amber-400/14";
}

export function computeDagrePositions(
  apiNodes: ApiNode[],
  apiEdges: ApiEdge[],
): Map<string, { x: number; y: number }> {
  const nodeIdSet = new Set(apiNodes.map((n) => n.id));
  const g = new dagre.graphlib.Graph();
  const rankdir = hasInheritsEdges(apiEdges) ? "TB" : "LR";
  g.setGraph({ rankdir, nodesep: 60, ranksep: 80, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));

  for (const n of apiNodes) {
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const e of apiEdges) {
    if (nodeIdSet.has(e.source) && nodeIdSet.has(e.target)) {
      g.setEdge(e.source, e.target);
    }
  }
  dagre.layout(g);

  const positions = new Map<string, { x: number; y: number }>();
  for (const n of apiNodes) {
    const pos = g.node(n.id);
    positions.set(n.id, {
      x: (pos?.x ?? 0) - NODE_WIDTH / 2,
      y: (pos?.y ?? 0) - NODE_HEIGHT / 2,
    });
  }
  return positions;
}

export function applyNodeStyles(
  apiNodes: ApiNode[],
  positions: Map<string, { x: number; y: number }>,
  isDark: boolean,
  highlightUids?: Set<string>,
): Node[] {
  const PALETTE = paletteForTheme(isDark);
  return apiNodes.map((n) => {
    const nt = normalizeGraphType(n.type);
    const colors = PALETTE[nt];
    const pos = positions.get(n.id) ?? { x: 0, y: 0 };
    const hl = highlightUids?.has(n.id);
    const ring = hl
      ? isDark
        ? "0 0 0 3px #fbbf24, 0 2px 8px rgba(0,0,0,0.35)"
        : "0 0 0 3px #d97706, 0 2px 8px rgba(0,0,0,0.12)"
      : n.is_center
        ? `0 0 20px ${colors.border}60`
        : `0 2px 8px rgba(0,0,0,0.12)`;
    return {
      id: n.id,
      position: pos,
      data: {
        label: n.name,
        type: n.type,
        file: n.file,
        line: n.line,
        end_line: n.end_line,
        signature: n.signature,
        docstring: n.docstring,
        isCenter: n.is_center,
      },
      style: {
        background: n.is_center ? colors.border : colors.bg,
        color: colors.text,
        border: `2px solid ${hl ? (isDark ? "#fbbf24" : "#d97706") : colors.border}`,
        borderRadius: "8px",
        padding: "8px 14px",
        fontSize: "12px",
        fontWeight: n.is_center ? 700 : 500,
        boxShadow: ring,
        minWidth: "80px",
        textAlign: "center" as const,
      },
    };
  });
}

export function buildFlowNodesWithDagre(
  apiNodes: ApiNode[],
  apiEdges: ApiEdge[],
  isDark: boolean,
  highlightUids?: Set<string>,
): Node[] {
  const positions = computeDagrePositions(apiNodes, apiEdges);
  return applyNodeStyles(apiNodes, positions, isDark, highlightUids);
}

export function buildFlowEdges(
  apiEdges: ApiEdge[],
  nodeIds: Set<string>,
  showLabels: boolean,
  isDark: boolean,
): Edge[] {
  const labelFill = isDark ? "#94a3b8" : "#64748b";
  const labelBg = isDark ? "#1e293b" : "#f8fafc";
  return apiEdges
    .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
    .map((e) => ({
      id: `e-${e.source}-${e.type || "rel"}-${e.target}`,
      source: e.source,
      target: e.target,
      label: showLabels ? e.type : undefined,
      animated: e.type === "CALLS",
      style: { stroke: EDGE_COLORS[e.type] || "#64748b", strokeWidth: 1.5 },
      labelStyle: showLabels ? { fontSize: 10, fill: labelFill } : undefined,
      labelBgStyle: showLabels ? { fill: labelBg, fillOpacity: 0.92 } : undefined,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: EDGE_COLORS[e.type] || "#64748b",
        width: 16,
        height: 16,
      },
    }));
}

export function truncateDoc(s: string, max = 280): string {
  const t = s.trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max)}…`;
}
