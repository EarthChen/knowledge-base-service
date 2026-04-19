import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import { Link } from "react-router-dom";
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
import { Network, Search, ZoomIn, Loader2, Eye, EyeOff } from "lucide-react";
import { useGraphExplore } from "../api/hooks";
import { useI18n } from "../i18n/context";
import type { GraphNode as ApiNode, GraphEdge as ApiEdge } from "../api/types";

type NodeTypeKey = "Function" | "Class" | "Module" | "Document";

const TYPE_FLOW_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  Function: { bg: "#ecfdf5", border: "#10b981", text: "#065f46" },
  Class: { bg: "#f0f9ff", border: "#0ea5e9", text: "#0c4a6e" },
  Module: { bg: "#faf5ff", border: "#a855f7", text: "#581c87" },
  Document: { bg: "#fffbeb", border: "#fbbf24", text: "#92400e" },
  Unknown: { bg: "#f1f5f9", border: "#64748b", text: "#334155" },
};

const EDGE_COLORS: Record<string, string> = {
  CALLS: "#10b981",
  INHERITS: "#0ea5e9",
  IMPORTS: "#a855f7",
  CONTAINS: "#fbbf24",
  REFERENCES: "#ef4444",
  USES_TYPE: "#ec4899",
};

const DEFAULT_VISIBILITY: Record<NodeTypeKey, boolean> = {
  Function: true,
  Class: true,
  Module: true,
  Document: true,
};

function normalizeGraphType(raw: string): keyof typeof TYPE_FLOW_COLORS {
  const t = raw?.trim();
  if (t === "Function" || t === "Class" || t === "Module" || t === "Document") return t;
  return "Unknown";
}

function buildFlowNodes(apiNodes: ApiNode[]): Node[] {
  const cols = Math.max(Math.ceil(Math.sqrt(apiNodes.length)), 1);
  return apiNodes.map((n, i) => {
    const nt = normalizeGraphType(n.type);
    const colors = TYPE_FLOW_COLORS[nt];
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
        end_line: n.end_line,
        signature: n.signature,
        docstring: n.docstring,
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
          : `0 2px 8px rgba(0,0,0,0.12)`,
        minWidth: "80px",
        textAlign: "center" as const,
      },
    };
  });
}

function buildFlowEdges(apiEdges: ApiEdge[], nodeIds: Set<string>, showLabels: boolean): Edge[] {
  return apiEdges
    .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
    .map((e, i) => ({
      id: `e-${i}-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      label: showLabels ? e.type : undefined,
      animated: e.type === "CALLS",
      style: { stroke: EDGE_COLORS[e.type] || "#64748b", strokeWidth: 1.5 },
      labelStyle: showLabels ? { fontSize: 10, fill: "#64748b" } : undefined,
      labelBgStyle: showLabels ? { fill: "#f8fafc", fillOpacity: 0.92 } : undefined,
      markerEnd: { type: MarkerType.ArrowClosed, color: EDGE_COLORS[e.type] || "#64748b", width: 16, height: 16 },
    }));
}

function truncateDoc(s: string, max = 280): string {
  const t = s.trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max)}…`;
}

export default function GraphExplorer() {
  const [searchName, setSearchName] = useState("");
  const [depth, setDepth] = useState(2);
  const [limit, setLimit] = useState(100);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [typeVisible, setTypeVisible] = useState<Record<NodeTypeKey, boolean>>({ ...DEFAULT_VISIBILITY });
  const [showEdgeLabels, setShowEdgeLabels] = useState(true);

  const apiNodesRef = useRef<Map<string, ApiNode>>(new Map());
  const edgesRef = useRef<ApiEdge[]>([]);
  const showEdgeLabelsRef = useRef(showEdgeLabels);
  const typeVisibleRef = useRef(typeVisible);

  useEffect(() => {
    showEdgeLabelsRef.current = showEdgeLabels;
  }, [showEdgeLabels]);

  useEffect(() => {
    typeVisibleRef.current = typeVisible;
  }, [typeVisible]);

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
            apiNodesRef.current = new Map(data.nodes.map((n) => [n.id, n]));
            edgesRef.current = data.edges;
            const built = buildFlowNodes(data.nodes);
            const flowNodes = built.map((n) => {
              const nt = normalizeGraphType((n.data?.type as string) || "");
              let vis = true;
              if (nt !== "Unknown") vis = typeVisibleRef.current[nt as NodeTypeKey];
              return { ...n, hidden: !vis };
            });
            const nodeIds = new Set(data.nodes.map((n) => n.id));
            const flowEdges = buildFlowEdges(data.edges, nodeIds, showEdgeLabelsRef.current);
            setNodes(flowNodes);
            setEdges(flowEdges);
            setSelectedNodeId(null);
          },
        },
      );
    },
    [depth, limit, mutation, setNodes, setEdges],
  );

  useEffect(() => {
    const data = mutation.data;
    if (!data?.nodes?.length) return;
    const nodeIds = new Set(data.nodes.map((n) => n.id));
    setEdges(buildFlowEdges(edgesRef.current, nodeIds, showEdgeLabels));
  }, [showEdgeLabels, mutation.data, setEdges]);

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
    setSelectedNodeId(node.id);
  }, []);

  const toggleType = useCallback((key: NodeTypeKey) => {
    setTypeVisible((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  useEffect(() => {
    setNodes((nds) =>
      nds.map((n) => {
        const rawType = (n.data?.type as string) || "";
        const nt = normalizeGraphType(rawType);
        let visible = true;
        if (nt !== "Unknown") visible = typeVisible[nt as NodeTypeKey];
        return { ...n, hidden: !visible };
      }),
    );
  }, [typeVisible, setNodes]);

  const selectedApiNode = selectedNodeId ? apiNodesRef.current.get(selectedNodeId) : undefined;

  const legend = useMemo(
    () => [
      { type: "Function" as const, color: TYPE_FLOW_COLORS.Function.border },
      { type: "Class" as const, color: TYPE_FLOW_COLORS.Class.border },
      { type: "Module" as const, color: TYPE_FLOW_COLORS.Module.border },
      { type: "Document" as const, color: TYPE_FLOW_COLORS.Document.border },
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

  const chipBase =
    "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors";

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
          <Network size={20} /> {t.explorer.title}
        </h2>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <span>
            {nodes.filter((n) => !n.hidden).length} {t.explorer.nodes} · {edges.length}{" "}
            {t.explorer.edges}
          </span>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
        <label className="flex-1 min-w-[200px]">
          <span className="mb-1 block text-xs font-medium text-gray-500">{t.explorer.entityName}</span>
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
          <span className="mb-1 block text-xs font-medium text-gray-500">{t.explorer.depth}</span>
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
          <span className="mb-1 block text-xs font-medium text-gray-500">{t.explorer.limit}</span>
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

      <div ref={containerRef} className="flex min-h-[500px] flex-1 flex-col gap-3 lg:flex-row">
        <div className="flex min-h-[500px] min-w-0 flex-1 flex-col gap-2">
          {nodes.length > 0 ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[11px] font-medium text-gray-500">{t.explorer.filterHint}:</span>
                {(
                  [
                    ["Function", t.explorer.typeFunction, TYPE_FLOW_COLORS.Function.border],
                    ["Class", t.explorer.typeClass, TYPE_FLOW_COLORS.Class.border],
                    ["Module", t.explorer.typeModule, TYPE_FLOW_COLORS.Module.border],
                    ["Document", t.explorer.typeDocument, TYPE_FLOW_COLORS.Document.border],
                  ] as const
                ).map(([key, label, color]) => {
                  const on = typeVisible[key];
                  return (
                    <button
                      key={key}
                      type="button"
                      onClick={() => toggleType(key)}
                      className={`${chipBase} ${
                        on
                          ? "border-gray-200 bg-white text-gray-800 shadow-sm"
                          : "border-gray-100 bg-gray-100 text-gray-400 line-through"
                      }`}
                    >
                      <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
                      {label}
                    </button>
                  );
                })}
                <button
                  type="button"
                  onClick={() => setShowEdgeLabels((v) => !v)}
                  className={`${chipBase} ml-auto border-gray-200 bg-white text-gray-700 shadow-sm`}
                >
                  {showEdgeLabels ? <Eye size={14} /> : <EyeOff size={14} />}
                  {t.explorer.edgeLabelToggle}: {showEdgeLabels ? t.explorer.edgeLabelsOn : t.explorer.edgeLabelsOff}
                </button>
              </div>

              <div className="min-h-[480px] flex-1 rounded-xl border border-gray-200 bg-gray-50 overflow-hidden">
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
                      const typ = normalizeGraphType((n.data?.type as string) || "");
                      return TYPE_FLOW_COLORS[typ]?.border || "#64748b";
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
                </ReactFlow>
              </div>
            </>
          ) : (
            <div className="flex min-h-[500px] flex-1 items-center justify-center rounded-xl border border-gray-200 bg-gray-50 text-gray-500">
              <div className="text-center">
                <Network size={48} className="mx-auto mb-3 opacity-30" />
                <p className="text-sm">{t.explorer.emptyHint}</p>
              </div>
            </div>
          )}
        </div>

        {selectedApiNode ? (
          <aside className="w-full shrink-0 rounded-xl border border-gray-200 bg-white p-4 shadow-sm lg:w-80">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">{t.explorer.panelTitle}</h3>
            <div className="mt-3 flex items-start justify-between gap-2">
              <p className="break-all text-sm font-semibold text-gray-900">{selectedApiNode.name}</p>
              <span
                className="shrink-0 rounded-md px-2 py-0.5 text-[10px] font-medium"
                style={{
                  backgroundColor:
                    TYPE_FLOW_COLORS[normalizeGraphType(selectedApiNode.type)]?.bg ?? "#f1f5f9",
                  color: TYPE_FLOW_COLORS[normalizeGraphType(selectedApiNode.type)]?.text ?? "#334155",
                  border: `1px solid ${TYPE_FLOW_COLORS[normalizeGraphType(selectedApiNode.type)]?.border ?? "#64748b"}`,
                }}
              >
                {selectedApiNode.type}
              </span>
            </div>

            {selectedApiNode.file ? (
              <p className="mt-2 break-all text-xs text-gray-600">{selectedApiNode.file}</p>
            ) : null}

            <p className="mt-2 text-xs text-gray-700">
              <span className="font-medium text-gray-500">{t.explorer.panelLineRange}: </span>
              {selectedApiNode.line != null
                ? selectedApiNode.end_line != null && selectedApiNode.end_line !== selectedApiNode.line
                  ? `${selectedApiNode.line}–${selectedApiNode.end_line}`
                  : String(selectedApiNode.line)
                : "—"}
            </p>

            {selectedApiNode.signature ? (
              <div className="mt-3">
                <p className="text-[11px] font-medium text-gray-500">{t.explorer.panelSignature}</p>
                <pre className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap break-all rounded-md bg-gray-50 p-2 text-[11px] text-gray-800">
                  {selectedApiNode.signature}
                </pre>
              </div>
            ) : null}

            {selectedApiNode.docstring ? (
              <div className="mt-3">
                <p className="text-[11px] font-medium text-gray-500">{t.explorer.panelDocstring}</p>
                <p className="mt-1 text-xs leading-relaxed text-gray-700">
                  {truncateDoc(selectedApiNode.docstring)}
                </p>
              </div>
            ) : null}

            <div className="mt-4 flex flex-col gap-2">
              <Link
                to={selectedApiNode.name ? `/wiki?q=${encodeURIComponent(selectedApiNode.name)}` : "/wiki"}
                className="inline-flex items-center justify-center rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs font-medium text-sky-900 hover:bg-sky-100"
              >
                {t.explorer.openInWiki}
              </Link>
              <Link
                to={selectedApiNode.name ? `/search?q=${encodeURIComponent(selectedApiNode.name)}` : "/search"}
                className="inline-flex items-center justify-center rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-800 hover:bg-gray-50"
              >
                <Search size={14} className="mr-1.5 inline" />
                {t.explorer.searchRelated}
              </Link>
            </div>

            <p className="mt-4 text-[10px] text-gray-400">{t.explorer.doubleClickHint}</p>
          </aside>
        ) : null}
      </div>
    </div>
  );
}
