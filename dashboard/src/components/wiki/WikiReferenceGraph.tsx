import { useCallback, useLayoutEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  ReactFlow,
  Background,
  Controls,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";
import { Loader2, GitBranch } from "lucide-react";
import { useWikiReferenceGraph, wikiReferenceGraphLayoutConstants } from "../../hooks/useWikiReferenceGraph";
import { useI18n } from "../../i18n/context";
import { getErrorMessage } from "../../utils/errorUtils";
import { wikiHref } from "./wikiRouteHelpers";

type Props = {
  businessId: string;
  view: "business_domain" | "code_structure";
};

const { NODE_W, NODE_H } = wikiReferenceGraphLayoutConstants;

function layoutDagre(nodes: Node[], edges: Edge[]): Node[] {
  if (!nodes.length) return [];
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 50, ranksep: 60, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of nodes) {
    g.setNode(n.id, { width: NODE_W, height: NODE_H });
  }
  for (const e of edges) {
    g.setEdge(e.source, e.target);
  }
  try {
    dagre.layout(g);
  } catch {
    return nodes;
  }
  return nodes.map((n) => {
    const pos = g.node(n.id);
    if (!pos) return n;
    return {
      ...n,
      position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 },
    };
  });
}

export default function WikiReferenceGraph({ businessId, view }: Props) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { nodes: rawNodes, edges, isLoading, isError, error, refetch, graph } = useWikiReferenceGraph(businessId);
  const [nodes, setNodes, onNodesChange] = useNodesState([] as Node[]);
  const [xyEdges, setXyEdges, onEdgesChange] = useEdgesState(edges);

  useLayoutEffect(() => {
    if (!rawNodes.length) {
      setNodes([]);
      return;
    }
    const next = layoutDagre(rawNodes, edges);
    setNodes(next);
  }, [rawNodes, edges, setNodes]);

  useLayoutEffect(() => {
    setXyEdges(edges);
  }, [edges, setXyEdges]);

  const onNodeClick: import("@xyflow/react").NodeMouseHandler = useCallback(
    (_e, node) => {
      const p = (node.data as { path?: string })?.path;
      if (typeof p === "string" && p) {
        const params: Record<string, string> = { business_id: businessId };
        if (view === "code_structure") params.view = "code_structure";
        navigate(wikiHref(p, params));
      }
    },
    [businessId, navigate, view],
  );

  const empty = useMemo(
    () => !isLoading && (graph?.pages?.length ?? 0) === 0,
    [isLoading, graph?.pages?.length],
  );

  if (isLoading) {
    return (
      <div className="flex h-[min(480px,60vh)] items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        {t.common.loading}
      </div>
    );
  }
  if (isError) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50/80 p-4 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-200">
        {getErrorMessage(error, t.common.unexpectedError)}
        <button
          type="button"
          onClick={() => void refetch()}
          className="ml-2 text-xs font-medium text-red-900 underline dark:text-red-200"
        >
          {t.common.retry}
        </button>
      </div>
    );
  }
  if (empty) {
    return (
      <div className="flex min-h-40 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-gray-200 p-6 text-sm text-gray-500 dark:border-gray-600 dark:text-gray-400">
        <GitBranch className="size-6 opacity-50" aria-hidden />
        {t.wiki.refGraphEmpty}
      </div>
    );
  }

  return (
    <div className="h-[min(480px,60vh)] w-full min-h-[280px] overflow-hidden rounded-xl border border-gray-200 bg-slate-50/80 dark:border-gray-700 dark:bg-gray-900/50">
      <p className="px-3 py-2 text-xs text-gray-500 dark:text-gray-400">{t.wiki.refGraphHint}</p>
      <ReactFlow
        nodes={nodes}
        edges={xyEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        fitView
        minZoom={0.2}
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
