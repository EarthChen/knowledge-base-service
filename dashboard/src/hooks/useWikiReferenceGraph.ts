import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { MarkerType, type Edge, type Node } from "@xyflow/react";
import { api } from "../api/client";
import type { WikiRefGraphResponse } from "./wikiTypes";

const NODE_W = 180;
const NODE_H = 44;

export type WikiReferenceGraphResult = {
  graph: WikiRefGraphResponse | undefined;
  nodes: Node[];
  edges: Edge[];
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  refetch: () => void;
};

function tierStyle(tier: string | undefined): { border: string; background: string; color: string } {
  const t = (tier || "").toLowerCase();
  if (t === "core") {
    return { border: "#2563eb", background: "#eff6ff", color: "#1e3a8a" };
  }
  if (t === "standard") {
    return { border: "#16a34a", background: "#f0fdf4", color: "#14532d" };
  }
  return { border: "#64748b", background: "#f1f5f9", color: "#334155" };
}

/** Fetch wiki references and build xyflow nodes/edges (layout positions are (0,0); component runs dagre). */
export function useWikiReferenceGraph(
  businessId: string,
): WikiReferenceGraphResult {
  const q = useQuery<WikiRefGraphResponse>({
    queryKey: ["wiki", "references", "graph", businessId],
    queryFn: () =>
      api<WikiRefGraphResponse>(`/wiki/references?business_id=${encodeURIComponent(businessId)}`),
    enabled: !!businessId,
    staleTime: 30_000,
  });

  const { nodes, edges } = useMemo(() => {
    const g = q.data;
    if (!g?.pages?.length) {
      return { nodes: [] as Node[], edges: [] as Edge[] };
    }
    const page_map = new Map(
      g.pages.map((p) => [
        p.uid,
        {
          id: p.uid,
          type: "default" as const,
          position: { x: 0, y: 0 },
          data: {
            label: p.title || p.path,
            path: p.path,
            importance_tier: p.importance_tier,
            repository: p.repository,
          },
          style: {
            width: NODE_W,
            height: NODE_H,
            ...tierStyle(p.importance_tier),
            borderWidth: 2,
            borderRadius: 8,
            fontSize: 11,
            fontWeight: 500,
            padding: 6,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            textAlign: "center" as const,
          },
        },
      ]),
    );
    const ns = [...page_map.values()];

    const ids = new Set(ns.map((n) => n.id));
    const ed: Edge[] = (g.edges || [])
      .filter((e) => ids.has(e.source_uid) && ids.has(e.target_uid))
      .map((e, i) => ({
        id: `e-${e.source_uid}-${e.target_uid}-${i}`,
        source: e.source_uid,
        target: e.target_uid,
        type: "smoothstep" as const,
        markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12, color: "#94a3b8" },
        style: { stroke: "#94a3b8", strokeWidth: 1.25 },
      }));
    return { nodes: ns, edges: ed };
  }, [q.data]);

  return {
    graph: q.data,
    nodes,
    edges,
    isLoading: q.isLoading,
    isError: q.isError,
    error: q.error as Error | null,
    refetch: q.refetch,
  };
}

export const wikiReferenceGraphLayoutConstants = { NODE_W, NODE_H };
