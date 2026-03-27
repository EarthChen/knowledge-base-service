import { useState, useCallback, useMemo, useRef } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeMouseHandler,
  MarkerType,
  Panel,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Network, Search, ZoomIn, Loader2 } from "lucide-react";
import { useGraphExplore } from "../api/hooks";
import { useI18n } from "../i18n/context";
import type { GraphNode as ApiNode, GraphEdge as ApiEdge } from "../api/types";

const NODE_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  Function: { bg: "#e0f2fe", border: "#0ea5e9", text: "#0c4a6e" },
  Class:    { bg: "#faf5ff", border: "#a855f7", text: "#581c87" },
  Module:   { bg: "#ecfdf5", border: "#22c55e", text: "#14532d" },
  Unknown:  { bg: "#f1f5f9", border: "#64748b", text: "#334155" },
};

const EDGE_COLORS: Record<string, string> = {
  CALLS:      "#0ea5e9",
  INHERITS:   "#a855f7",
  IMPORTS:    "#22c55e",
  CONTAINS:   "#f59e0b",
  REFERENCES: "#ef4444",
  USES_TYPE:  "#ec4899",
};

function buildFlowNodes(apiNodes: ApiNode[]): Node[] {
  const cols = Math.max(Math.ceil(Math.sqrt(apiNodes.length)), 1);
  return apiNodes.map((n, i) => {
    const colors = NODE_COLORS[n.type] || NODE_COLORS.Unknown;
    const col = i % cols;
    const row = Math.floor(i / cols);
    return {
      id: n.id,
      position: { x: col * 260 + (Math.random() - 0.5) * 40, y: row * 120 + (Math.random() - 0.5) * 20 },
      data: {
        label: n.name,
        type: n.type,
        file: n.file,
        line: n.line,
        isCenter: n.is_center,
      },
      style: {
        background: n.is_center ? colors.border : colors.bg,
        color: colors.text,
        border: `2px solid ${colors.border}`,
        borderRadius: "8px",
        padding: "8px 14px",
        fontSize: "12px",
        fontWeight: n.is_center ? 700 : 500,
        boxShadow: n.is_center
          ? `0 0 20px ${colors.border}60`
          : `0 2px 8px rgba(0,0,0,0.3)`,
        minWidth: "80px",
        textAlign: "center" as const,
      },
    };
  });
}

function buildFlowEdges(apiEdges: ApiEdge[], nodeIds: Set<string>): Edge[] {
  return apiEdges
    .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
    .map((e, i) => ({
      id: `e-${i}-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      label: e.type,
      animated: e.type === "CALLS",
      style: { stroke: EDGE_COLORS[e.type] || "#64748b", strokeWidth: 1.5 },
      labelStyle: { fontSize: 10, fill: "#64748b" },
      labelBgStyle: { fill: "#f8fafc", fillOpacity: 0.92 },
      markerEnd: { type: MarkerType.ArrowClosed, color: EDGE_COLORS[e.type] || "#64748b", width: 16, height: 16 },
    }));
}

export default function GraphExplorer() {
  const [searchName, setSearchName] = useState("");
  const [depth, setDepth] = useState(2);
  const [limit, setLimit] = useState(100);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);

  const { t } = useI18n();
  const mutation = useGraphExplore();
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleExplore = useCallback(
    (name: string) => {
      mutation.mutate(
        { name: name.trim(), depth, limit },
        {
          onSuccess: (data) => {
            const flowNodes = buildFlowNodes(data.nodes);
            const nodeIds = new Set(data.nodes.map((n) => n.id));
            const flowEdges = buildFlowEdges(data.edges, nodeIds);
            setNodes(flowNodes);
            setEdges(flowEdges);
            setSelectedNode(null);
          },
        },
      );
    },
    [depth, limit, mutation, setNodes, setEdges],
  );

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (searchName.trim()) handleExplore(searchName.trim());
    },
    [searchName, handleExplore],
  );

  const onNodeDoubleClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      const name = node.data?.label as string;
      if (name) {
        setSearchName(name);
        handleExplore(name);
      }
    },
    [handleExplore],
  );

  const onNodeClick: NodeMouseHandler = useCallback((_event, node) => {
    setSelectedNode(node);
  }, []);

  const legend = useMemo(
    () => [
      { type: "Function", color: NODE_COLORS.Function.border },
      { type: "Class", color: NODE_COLORS.Class.border },
      { type: "Module", color: NODE_COLORS.Module.border },
    ],
    [],
  );

  const edgeLegend = useMemo(
    () =>
      Object.entries(EDGE_COLORS).map(([type, color]) => ({ type, color })),
    [],
  );

  const inputClass =
    "rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-300";

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
          <Network size={20} /> {t.explorer.title}
        </h2>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <span>
            {nodes.length} {t.explorer.nodes} · {edges.length} {t.explorer.edges}
          </span>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
        <label className="flex-1 min-w-[200px]">
          <span className="mb-1 block text-xs font-medium text-gray-500">
            {t.explorer.entityName}
          </span>
          <div className="relative">
            <Search
              size={16}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
            />
            <input
              type="text"
              value={searchName}
              onChange={(e) => setSearchName(e.target.value)}
              placeholder={t.explorer.searchPlaceholder}
              className={`w-full pl-9 ${inputClass}`}
            />
          </div>
        </label>
        <label>
          <span className="mb-1 block text-xs font-medium text-gray-500">
            {t.explorer.depth}
          </span>
          <input
            type="number"
            min={1}
            max={5}
            value={depth}
            onChange={(e) => setDepth(Number(e.target.value) || 2)}
            className={`w-20 ${inputClass}`}
          />
        </label>
        <label>
          <span className="mb-1 block text-xs font-medium text-gray-500">
            {t.explorer.limit}
          </span>
          <input
            type="number"
            min={10}
            max={500}
            step={10}
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value) || 100)}
            className={`w-24 ${inputClass}`}
          />
        </label>
        <button
          type="submit"
          disabled={mutation.isPending || !searchName.trim()}
          className="flex items-center gap-2 rounded-lg bg-sky-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:opacity-50"
        >
          {mutation.isPending ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <ZoomIn size={16} />
          )}
          {t.explorer.explore}
        </button>
      </form>

      {mutation.error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-600">
          {mutation.error.message}
        </div>
      )}

      <div
        ref={containerRef}
        className="flex-1 min-h-[500px] rounded-xl border border-gray-200 bg-gray-50 overflow-hidden"
      >
        {nodes.length > 0 ? (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            onNodeDoubleClick={onNodeDoubleClick}
            fitView
            fitViewOptions={{ padding: 0.3 }}
            minZoom={0.1}
            maxZoom={3}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#cbd5e1" gap={20} />
            <Controls
              showInteractive={false}
              style={{ background: "#f8fafc", borderColor: "#e2e8f0" }}
            />
            <MiniMap
              nodeColor={(n) => {
                const type = n.data?.type as string;
                return NODE_COLORS[type]?.border || "#64748b";
              }}
              style={{ background: "#f1f5f9", borderColor: "#e2e8f0" }}
              maskColor="rgba(241, 245, 249, 0.75)"
            />

            <Panel position="top-left" className="space-y-1.5">
              <div className="rounded-lg bg-white/90 border border-gray-200 px-3 py-2 backdrop-blur shadow-sm">
                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-gray-400">
                  {t.explorer.nodeTypes}
                </p>
                <div className="flex flex-wrap gap-x-3 gap-y-1">
                  {legend.map((l) => (
                    <span key={l.type} className="flex items-center gap-1.5 text-[11px] text-gray-500">
                      <span
                        className="inline-block h-2.5 w-2.5 rounded-sm"
                        style={{ backgroundColor: l.color }}
                      />
                      {l.type}
                    </span>
                  ))}
                </div>
                <p className="mt-2 mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-gray-400">
                  {t.explorer.edgeTypes}
                </p>
                <div className="flex flex-wrap gap-x-3 gap-y-1">
                  {edgeLegend.map((l) => (
                    <span key={l.type} className="flex items-center gap-1.5 text-[11px] text-gray-500">
                      <span
                        className="inline-block h-0.5 w-4 rounded-full"
                        style={{ backgroundColor: l.color }}
                      />
                      {l.type}
                    </span>
                  ))}
                </div>
              </div>
            </Panel>

            {selectedNode && (
              <Panel position="bottom-right">
                <div className="w-72 rounded-lg bg-white/95 border border-gray-300 p-3 backdrop-blur shadow-xl">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-gray-900">
                      {selectedNode.data?.label as string}
                    </span>
                    <span
                      className="rounded px-1.5 py-0.5 text-[10px] font-medium"
                      style={{
                        backgroundColor:
                          NODE_COLORS[selectedNode.data?.type as string]?.bg || "#f1f5f9",
                        color:
                          NODE_COLORS[selectedNode.data?.type as string]?.text || "#334155",
                        border: `1px solid ${
                          NODE_COLORS[selectedNode.data?.type as string]?.border || "#64748b"
                        }`,
                      }}
                    >
                      {selectedNode.data?.type as string}
                    </span>
                  </div>
                  {selectedNode.data?.file ? (
                    <p className="text-[11px] text-gray-500 truncate">
                      {String(selectedNode.data.file)}
                      {selectedNode.data?.line ? `:${String(selectedNode.data.line)}` : ""}
                    </p>
                  ) : null}
                  <p className="mt-2 text-[10px] text-gray-400">
                    {t.explorer.doubleClickHint}
                  </p>
                </div>
              </Panel>
            )}
          </ReactFlow>
        ) : (
          <div className="flex h-full items-center justify-center text-gray-500">
            <div className="text-center">
              <Network size={48} className="mx-auto mb-3 opacity-30" />
              <p className="text-sm">{t.explorer.emptyHint}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
