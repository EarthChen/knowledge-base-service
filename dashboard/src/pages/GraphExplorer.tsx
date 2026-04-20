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
import dagre from "@dagrejs/dagre";
import { Network, Search, ZoomIn, Loader2, Eye, EyeOff, AlertTriangle, Undo2 } from "lucide-react";
import {
  useGraphExplore,
  useGraphExpand,
  useBlastRadius,
  useGraphCommunities,
  useRepositories,
} from "../api/hooks";
import { useI18n } from "../i18n/context";
import type {
  GraphNode as ApiNode,
  GraphEdge as ApiEdge,
  CommunityInfo,
} from "../api/types";

type NodeTypeKey = "Function" | "Class" | "Module" | "Document";

const TYPE_FLOW_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  Function: { bg: "#ecfdf5", border: "#10b981", text: "#065f46" },
  Class: { bg: "#f0f9ff", border: "#0ea5e9", text: "#0c4a6e" },
  Module: { bg: "#faf5ff", border: "#a855f7", text: "#581c87" },
  Document: { bg: "#fffbeb", border: "#fbbf24", text: "#92400e" },
  Unknown: { bg: "#f1f5f9", border: "#64748b", text: "#334155" },
};

const TYPE_FLOW_COLORS_DARK: Record<string, { bg: string; border: string; text: string }> = {
  Function: { bg: "#064e3c", border: "#34d399", text: "#d1fae5" },
  Class: { bg: "#0c4a6e", border: "#38bdf8", text: "#e0f2fe" },
  Module: { bg: "#581c87", border: "#c084fc", text: "#f3e8ff" },
  Document: { bg: "#78350f", border: "#fbbf24", text: "#fef3c7" },
  Unknown: { bg: "#1e293b", border: "#94a3b8", text: "#e2e8f0" },
};

function paletteForTheme(isDark: boolean) {
  return isDark ? TYPE_FLOW_COLORS_DARK : TYPE_FLOW_COLORS;
}

function useHtmlClassDark(): boolean {
  const [dark, setDark] = useState(
    () => typeof document !== "undefined" && document.documentElement.classList.contains("dark"),
  );
  useEffect(() => {
    const el = document.documentElement;
    const sync = () => setDark(el.classList.contains("dark"));
    sync();
    const mo = new MutationObserver(sync);
    mo.observe(el, { attributes: true, attributeFilter: ["class"] });
    return () => mo.disconnect();
  }, []);
  return dark;
}

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

/** Initial paint cap for POST /graph/explore results (progressive expansion adds more). */
const INITIAL_NODE_LIMIT = 50;
/** Hard safety cap to prevent browser tab from exhausting memory. */
const MAX_GRAPH_NODES = 500;
const NODE_WIDTH = 160;
const NODE_HEIGHT = 48;

function mergeGraphEdges(existing: ApiEdge[], incoming: ApiEdge[]): ApiEdge[] {
  const key = (e: ApiEdge) => `${e.source}|${e.type}|${e.target}`;
  const out = new Map<string, ApiEdge>();
  for (const e of existing) out.set(key(e), e);
  for (const e of incoming) out.set(key(e), e);
  return [...out.values()];
}

function normalizeGraphType(raw: string): keyof typeof TYPE_FLOW_COLORS {
  const t = raw?.trim();
  if (t === "Function" || t === "Class" || t === "Module" || t === "Document") return t;
  return "Unknown";
}

function hasInheritsEdges(apiEdges: ApiEdge[]): boolean {
  return apiEdges.some((e) => e.type === "INHERITS");
}

function depthRowClass(depth: number, maxDepth: number): string {
  if (maxDepth <= 1) {
    return "bg-amber-500/25 dark:bg-amber-400/30";
  }
  const step = (depth - 1) / Math.max(maxDepth - 1, 1);
  if (step <= 0.34) return "bg-amber-500/30 dark:bg-amber-400/35";
  if (step <= 0.67) return "bg-amber-500/18 dark:bg-amber-400/22";
  return "bg-amber-500/10 dark:bg-amber-400/14";
}

function buildFlowNodesWithDagre(
  apiNodes: ApiNode[],
  apiEdges: ApiEdge[],
  isDark: boolean,
  highlightUids?: Set<string>,
): Node[] {
  const PALETTE = paletteForTheme(isDark);
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

  const nodes: Node[] = apiNodes.map((n) => {
    const nt = normalizeGraphType(n.type);
    const colors = PALETTE[nt];
    const pos = g.node(n.id);
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
      position: {
        x: (pos?.x ?? 0) - NODE_WIDTH / 2,
        y: (pos?.y ?? 0) - NODE_HEIGHT / 2,
      },
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
  return nodes;
}

function buildFlowEdges(
  apiEdges: ApiEdge[],
  nodeIds: Set<string>,
  showLabels: boolean,
  isDark: boolean,
): Edge[] {
  const labelFill = isDark ? "#94a3b8" : "#64748b";
  const labelBg = isDark ? "#1e293b" : "#f8fafc";
  return apiEdges
    .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
    .map((e, i) => ({
      id: `e-${i}-${e.source}-${e.target}`,
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
  /** True when last explore returned more nodes than INITIAL_NODE_LIMIT (only first N painted). */
  const [initialSliceHint, setInitialSliceHint] = useState(false);
  const [expandHistory, setExpandHistory] = useState<string[][]>([]);
  const [blastNamesInput, setBlastNamesInput] = useState("");
  const [blastDepth, setBlastDepth] = useState(3);
  const [blastRepo, setBlastRepo] = useState("");
  const [communityRepo, setCommunityRepo] = useState("");
  const [communityMinSize, setCommunityMinSize] = useState(3);
  const [communityHighlight, setCommunityHighlight] = useState<Set<string>>(new Set());
  const [selectedCommunityKey, setSelectedCommunityKey] = useState<number | null>(null);

  const apiNodesRef = useRef<Map<string, ApiNode>>(new Map());
  const edgesRef = useRef<ApiEdge[]>([]);
  const visibleNodeIdsRef = useRef<Set<string>>(new Set());
  const showEdgeLabelsRef = useRef(showEdgeLabels);
  const typeVisibleRef = useRef(typeVisible);

  useEffect(() => {
    showEdgeLabelsRef.current = showEdgeLabels;
  }, [showEdgeLabels]);

  useEffect(() => {
    typeVisibleRef.current = typeVisible;
  }, [typeVisible]);

  const { t } = useI18n();
  const isDark = useHtmlClassDark();
  const mutation = useGraphExplore();
  const expandMutation = useGraphExpand();
  const blastMutation = useBlastRadius();
  const communitiesMutation = useGraphCommunities();
  const reposQuery = useRepositories();
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const containerRef = useRef<HTMLDivElement>(null);

  const applyGraphLayout = useCallback(() => {
    const list = [...apiNodesRef.current.values()];
    const builtNodes = buildFlowNodesWithDagre(
      list,
      edgesRef.current,
      isDark,
      communityHighlight.size ? communityHighlight : undefined,
    );
    const flowNodes = builtNodes.map((n) => {
      const nt = normalizeGraphType((n.data?.type as string) || "");
      let vis = true;
      if (nt !== "Unknown") vis = typeVisibleRef.current[nt as NodeTypeKey];
      return { ...n, hidden: !vis };
    });
    const nodeIds = new Set(builtNodes.map((n) => n.id));
    visibleNodeIdsRef.current = nodeIds;
    const flowEdges = buildFlowEdges(
      edgesRef.current,
      nodeIds,
      showEdgeLabelsRef.current,
      isDark,
    );
    setNodes(flowNodes);
    setEdges(flowEdges);
  }, [isDark, communityHighlight, setNodes, setEdges]);

  const handleExplore = useCallback(
    (name: string) => {
      mutation.mutate(
        { name: name.trim(), depth, limit },
        {
          onSuccess: (data) => {
            expandMutation.reset();
            setExpandHistory([]);
            const overflow = data.nodes.length > INITIAL_NODE_LIMIT;
            setInitialSliceHint(overflow);
            const slice = overflow ? data.nodes.slice(0, INITIAL_NODE_LIMIT) : data.nodes;
            apiNodesRef.current = new Map(slice.map((n) => [n.id, n]));
            const idset = new Set(slice.map((n) => n.id));
            edgesRef.current = data.edges.filter(
              (e) => idset.has(e.source) && idset.has(e.target),
            );
            applyGraphLayout();
            setSelectedNodeId(null);
          },
        },
      );
    },
    [depth, limit, mutation, expandMutation, applyGraphLayout],
  );

  useEffect(() => {
    if (apiNodesRef.current.size === 0) return;
    applyGraphLayout();
  }, [communityHighlight, applyGraphLayout]);

  const handleBlastRadius = useCallback(() => {
    const names = blastNamesInput
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (!names.length) return;
    blastMutation.mutate({
      entity_names: names,
      max_depth: blastDepth,
      repository: blastRepo.trim() || null,
    });
  }, [blastNamesInput, blastDepth, blastRepo, blastMutation]);

  const handleLoadCommunities = useCallback(() => {
    communitiesMutation.mutate({
      repository: communityRepo.trim() || null,
      min_size: communityMinSize,
    });
  }, [communityRepo, communityMinSize, communitiesMutation]);

  const handleCommunityClick = useCallback((c: CommunityInfo) => {
    setSelectedCommunityKey(c.id);
    setCommunityHighlight(new Set(c.members.map((m) => m.uid)));
  }, []);

  const handleExpandNeighbors = useCallback(
    (nodeLabel: string, expandLimit: number) => {
      const label = nodeLabel.trim();
      if (!label) return;
      if (apiNodesRef.current.size >= MAX_GRAPH_NODES) return;
      const existingUids = [...apiNodesRef.current.keys()];
      const selectedNode = apiNodesRef.current.get(
        [...apiNodesRef.current.entries()].find(([, n]) => n.name === label)?.[0] ?? "",
      );
      expandMutation.mutate(
        {
          node_name: label,
          center_uid: selectedNode?.id,
          limit: expandLimit,
          depth: 1,
          exclude_uids: existingUids,
        },
        {
          onSuccess: (result) => {
            const newBatch: string[] = [];
            for (const n of result.nodes) {
              if (!apiNodesRef.current.has(n.id)) {
                apiNodesRef.current.set(n.id, n);
                newBatch.push(n.id);
              }
            }
            edgesRef.current = mergeGraphEdges(edgesRef.current, result.edges);
            if (newBatch.length) {
              setExpandHistory((h) => [...h, newBatch]);
            }
            applyGraphLayout();
          },
        },
      );
    },
    [expandMutation, applyGraphLayout],
  );

  const handleUndoExpand = useCallback(() => {
    if (expandHistory.length === 0) return;
    const lastBatch = expandHistory[expandHistory.length - 1];
    for (const uid of lastBatch) {
      apiNodesRef.current.delete(uid);
    }
    const idset = new Set(apiNodesRef.current.keys());
    edgesRef.current = edgesRef.current.filter(
      (e) => idset.has(e.source) && idset.has(e.target),
    );
    setExpandHistory((h) => h.slice(0, -1));
    setSelectedNodeId((sid) => (sid && !apiNodesRef.current.has(sid) ? null : sid));
    applyGraphLayout();
  }, [expandHistory, applyGraphLayout]);

  useEffect(() => {
    if (!visibleNodeIdsRef.current.size) return;
    setEdges(
      buildFlowEdges(edgesRef.current, visibleNodeIdsRef.current, showEdgeLabels, isDark),
    );
  }, [showEdgeLabels, isDark, setEdges]);

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
      if (name && !expandMutation.isPending) {
        handleExpandNeighbors(name, 20);
      }
    },
    [handleExpandNeighbors, expandMutation.isPending],
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
        const PALETTE = paletteForTheme(isDark);
        const colors = PALETTE[nt];
        const isCenter = Boolean(n.data?.isCenter);
        const hl = communityHighlight.has(n.id);
        const borderC = hl ? (isDark ? "#fbbf24" : "#d97706") : colors.border;
        const boxShadow = hl
          ? isDark
            ? "0 0 0 3px #fbbf24, 0 2px 8px rgba(0,0,0,0.35)"
            : "0 0 0 3px #d97706, 0 2px 8px rgba(0,0,0,0.12)"
          : isCenter
            ? `0 0 20px ${colors.border}60`
            : `0 2px 8px rgba(0,0,0,0.12)`;
        return {
          ...n,
          hidden: !visible,
          style: {
            background: isCenter ? colors.border : colors.bg,
            color: colors.text,
            border: `2px solid ${borderC}`,
            borderRadius: "8px",
            padding: "8px 14px",
            fontSize: "12px",
            fontWeight: isCenter ? 700 : 500,
            boxShadow,
            minWidth: "80px",
            textAlign: "center" as const,
          },
        };
      }),
    );
  }, [typeVisible, isDark, communityHighlight, setNodes]);

  const selectedApiNode = selectedNodeId ? apiNodesRef.current.get(selectedNodeId) : undefined;

  const legend = useMemo(() => {
    const P = paletteForTheme(isDark);
    return [
      { type: "Function" as const, color: P.Function.border },
      { type: "Class" as const, color: P.Class.border },
      { type: "Module" as const, color: P.Module.border },
      { type: "Document" as const, color: P.Document.border },
    ];
  }, [isDark]);

  const edgeLegend = useMemo(
    () =>
      Object.entries(EDGE_COLORS).map(([type, color]) => ({ type, color })),
    [],
  );

  const inputClass =
    "rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-300 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 dark:placeholder-gray-500 dark:focus:border-sky-500 dark:focus:ring-sky-700";

  const chipBase =
    "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors dark:border-gray-600";

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-gray-100">
          <Network size={20} /> {t.explorer.title}
        </h2>
        <div className="flex items-center gap-2 text-xs text-gray-400 dark:text-gray-500">
          <span>
            {nodes.filter((n) => !n.hidden).length} {t.explorer.nodes} · {edges.length}{" "}
            {t.explorer.edges}
          </span>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3">
        <label className="flex-1 min-w-[200px]">
          <span className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">
            {t.explorer.entityName}
          </span>
          <div className="relative">
            <Search
              size={16}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 dark:text-gray-500"
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
          <span className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">{t.explorer.depth}</span>
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
          <span className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">{t.explorer.limit}</span>
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
          className="flex items-center gap-2 rounded-lg bg-sky-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:opacity-50 dark:bg-sky-500 dark:hover:bg-sky-400"
        >
          {mutation.isPending ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <ZoomIn size={16} />
          )}
          {t.explorer.explore}
        </button>
      </form>

      {initialSliceHint && (
        <div className="flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700 dark:border-amber-900/80 dark:bg-amber-950/60 dark:text-amber-200">
          <AlertTriangle size={16} className="shrink-0" aria-hidden />
          {t.explorer.expandMoreHint}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 text-sm">
        {expandMutation.isPending ? (
          <span className="flex items-center gap-2 text-sky-600 dark:text-sky-400">
            <Loader2 size={16} className="animate-spin shrink-0" aria-hidden />
            {t.explorer.expanding}
          </span>
        ) : null}
        {expandHistory.length > 0 ? (
          <button
            type="button"
            onClick={handleUndoExpand}
            disabled={expandMutation.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-800 shadow-sm transition-colors hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700"
          >
            <Undo2 size={14} aria-hidden />
            {t.explorer.undoExpand}
          </button>
        ) : null}
        {expandHistory.length > 0 ? (
          <span className="text-xs text-gray-600 dark:text-gray-400">
            {t.explorer.expandedCount.replace(
              "{count}",
              String(expandHistory.reduce((a, b) => a + b.length, 0)),
            )}
          </span>
        ) : null}
      </div>

      {mutation.error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-600 dark:border-red-900 dark:bg-red-950/60 dark:text-red-300">
          {mutation.error.message}
        </div>
      )}

      {expandMutation.error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-600 dark:border-red-900 dark:bg-red-950/60 dark:text-red-300">
          {expandMutation.error.message}
        </div>
      )}

      <div ref={containerRef} className="flex min-h-[500px] flex-1 flex-col gap-3 lg:flex-row">
        <aside className="flex w-full shrink-0 flex-col gap-4 lg:w-80">
          <section className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
              {t.explorer.blastTitle}
            </h3>
            <label className="mt-3 block">
              <span className="mb-1 block text-[11px] font-medium text-gray-500 dark:text-gray-400">
                {t.explorer.blastNamesLabel}
              </span>
              <textarea
                value={blastNamesInput}
                onChange={(e) => setBlastNamesInput(e.target.value)}
                rows={2}
                placeholder={t.explorer.blastNamesPlaceholder}
                className={`w-full resize-y ${inputClass}`}
              />
            </label>
            <div className="mt-2 flex flex-wrap gap-2">
              <label className="flex-1 min-w-[100px]">
                <span className="mb-1 block text-[11px] font-medium text-gray-500 dark:text-gray-400">
                  {t.explorer.blastMaxDepth}
                </span>
                <input
                  type="number"
                  min={1}
                  max={5}
                  value={blastDepth}
                  onChange={(e) => setBlastDepth(Number(e.target.value) || 3)}
                  className={`w-full ${inputClass}`}
                />
              </label>
              <label className="min-w-[140px] flex-1">
                <span className="mb-1 block text-[11px] font-medium text-gray-500 dark:text-gray-400">
                  {t.explorer.blastRepositoryOptional}
                </span>
                <input
                  type="text"
                  value={blastRepo}
                  onChange={(e) => setBlastRepo(e.target.value)}
                  className={`w-full ${inputClass}`}
                />
              </label>
            </div>
            <button
              type="button"
              onClick={handleBlastRadius}
              disabled={blastMutation.isPending || !blastNamesInput.trim()}
              className="mt-3 w-full rounded-lg bg-amber-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-amber-500 disabled:opacity-50 dark:bg-amber-500 dark:hover:bg-amber-400"
            >
              {blastMutation.isPending ? t.explorer.blastRunning : t.explorer.blastRun}
            </button>
            {blastMutation.error ? (
              <p className="mt-2 text-xs text-red-600 dark:text-red-400">{blastMutation.error.message}</p>
            ) : null}
            {blastMutation.data ? (
              <div className="mt-3 space-y-2 text-xs">
                <p className="font-medium text-gray-700 dark:text-gray-200">{t.explorer.blastAffectedTitle}</p>
                <p className="text-[11px] text-gray-600 dark:text-gray-400">
                  total {blastMutation.data.total_affected} · max depth {blastMutation.data.summary.max_depth_reached}
                </p>
                <p className="text-[11px] text-gray-600 dark:text-gray-400">
                  {Object.entries(blastMutation.data.summary.by_type)
                    .map(([k, v]) => `${k}: ${v}`)
                    .join(" · ")}
                </p>
                <p className="text-[11px] text-gray-600 dark:text-gray-400">
                  {Object.entries(blastMutation.data.summary.by_relation)
                    .map(([k, v]) => `${k}: ${v}`)
                    .join(" · ")}
                </p>
                {(() => {
                  const md = Math.max(
                    blastMutation.data.summary.max_depth_reached,
                    ...blastMutation.data.affected.map((l) => l.depth),
                    1,
                  );
                  return blastMutation.data.affected.map((layer) => (
                    <div key={layer.depth} className="space-y-1">
                      <p
                        className={`text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 ${depthRowClass(layer.depth, md)} rounded px-2 py-0.5`}
                      >
                        {t.explorer.depth} {layer.depth}
                      </p>
                      <ul className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-gray-100 dark:border-gray-700">
                        {layer.nodes.map((node) => (
                          <li
                            key={node.uid}
                            className={`break-all border-b border-gray-100 px-2 py-1.5 last:border-0 dark:border-gray-800 ${depthRowClass(layer.depth, md)}`}
                          >
                            <span className="font-medium text-gray-800 dark:text-gray-100">{node.name}</span>{" "}
                            <span className="text-gray-500 dark:text-gray-400">· {node.type}</span>
                            <br />
                            <span className="text-[10px] text-gray-500 dark:text-gray-500">
                              {t.explorer.blastRelation}: {node.relation} · {t.explorer.blastConfidence}:{" "}
                              {node.confidence}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ));
                })()}
              </div>
            ) : null}
          </section>

          <section className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
              {t.explorer.communityTitle}
            </h3>
            <label className="mt-3 block">
              <span className="mb-1 block text-[11px] font-medium text-gray-500 dark:text-gray-400">
                {t.explorer.communityRepository}
              </span>
              <select
                value={communityRepo}
                onChange={(e) => setCommunityRepo(e.target.value)}
                className={`w-full ${inputClass}`}
              >
                <option value="">{t.explorer.communityAllRepos}</option>
                {(reposQuery.data?.repositories ?? []).map((r) => (
                  <option key={r.repository} value={r.repository}>
                    {r.repository}
                  </option>
                ))}
              </select>
            </label>
            <label className="mt-2 block">
              <span className="mb-1 block text-[11px] font-medium text-gray-500 dark:text-gray-400">
                {t.explorer.communityMinSize}
              </span>
              <input
                type="number"
                min={2}
                max={50}
                value={communityMinSize}
                onChange={(e) => setCommunityMinSize(Number(e.target.value) || 3)}
                className={`w-full ${inputClass}`}
              />
            </label>
            <button
              type="button"
              onClick={handleLoadCommunities}
              disabled={communitiesMutation.isPending}
              className="mt-3 w-full rounded-lg border border-violet-300 bg-violet-50 px-3 py-2 text-sm font-medium text-violet-900 transition-colors hover:bg-violet-100 disabled:opacity-50 dark:border-violet-800 dark:bg-violet-950/60 dark:text-violet-100 dark:hover:bg-violet-900/60"
            >
              {communitiesMutation.isPending ? t.explorer.communityLoading : t.explorer.communityLoad}
            </button>
            {communitiesMutation.error ? (
              <p className="mt-2 text-xs text-red-600 dark:text-red-400">{communitiesMutation.error.message}</p>
            ) : null}
            {communitiesMutation.data ? (
              <div className="mt-3 space-y-2 text-xs">
                <p className="text-gray-600 dark:text-gray-300">
                  {t.explorer.communityUnclustered}: {communitiesMutation.data.unclustered_count}
                </p>
                <p className="text-[10px] text-gray-500 dark:text-gray-500">
                  {t.explorer.communityClickHighlight}
                </p>
                <ul className="max-h-48 space-y-1.5 overflow-y-auto">
                  {communitiesMutation.data.communities.map((c) => (
                    <li key={c.id}>
                      <button
                        type="button"
                        onClick={() => handleCommunityClick(c)}
                        className={`w-full rounded-lg border px-2 py-2 text-left text-xs transition-colors ${
                          selectedCommunityKey === c.id
                            ? "border-violet-500 bg-violet-50 dark:border-violet-500 dark:bg-violet-950/80"
                            : "border-gray-200 bg-gray-50 hover:bg-gray-100 dark:border-gray-600 dark:bg-gray-800 dark:hover:bg-gray-700"
                        }`}
                      >
                        <span className="font-medium text-gray-900 dark:text-gray-100">{c.label}</span>
                        <span className="ml-2 text-gray-500 dark:text-gray-400">
                          · n={c.size} · cohesion {c.cohesion}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="mt-3 text-[11px] text-gray-500 dark:text-gray-400">{t.explorer.communityEmpty}</p>
            )}
          </section>
        </aside>

        <div className="flex min-h-[500px] min-w-0 flex-1 flex-col gap-2">
          {nodes.length > 0 ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[11px] font-medium text-gray-500 dark:text-gray-400">
                  {t.explorer.filterHint}:
                </span>
                {(
                  [
                    ["Function", t.explorer.typeFunction, legend[0]!.color],
                    ["Class", t.explorer.typeClass, legend[1]!.color],
                    ["Module", t.explorer.typeModule, legend[2]!.color],
                    ["Document", t.explorer.typeDocument, legend[3]!.color],
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
                          ? "border-gray-200 bg-white text-gray-800 shadow-sm dark:border-gray-500 dark:bg-gray-800 dark:text-gray-100"
                          : "border-gray-100 bg-gray-100 text-gray-400 line-through dark:border-gray-700 dark:bg-gray-900/80 dark:text-gray-500"
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
                  className={`${chipBase} ml-auto border-gray-200 bg-white text-gray-700 shadow-sm dark:border-gray-500 dark:bg-gray-800 dark:text-gray-200`}
                >
                  {showEdgeLabels ? <Eye size={14} /> : <EyeOff size={14} />}
                  {t.explorer.edgeLabelToggle}: {showEdgeLabels ? t.explorer.edgeLabelsOn : t.explorer.edgeLabelsOff}
                </button>
              </div>

              <div className="min-h-[480px] flex-1 overflow-hidden rounded-xl border border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-slate-900">
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
                  <Background color={isDark ? "#475569" : "#cbd5e1"} gap={20} />
                  <Controls
                    showInteractive={false}
                    style={
                      isDark
                        ? { background: "#1e293b", borderColor: "#334155" }
                        : { background: "#f8fafc", borderColor: "#e2e8f0" }
                    }
                  />
                  <MiniMap
                    nodeColor={(n) => {
                      const typ = normalizeGraphType((n.data?.type as string) || "");
                      const P = paletteForTheme(isDark);
                      return P[typ]?.border || "#64748b";
                    }}
                    style={
                      isDark
                        ? { background: "#0f172a", borderColor: "#334155" }
                        : { background: "#f1f5f9", borderColor: "#e2e8f0" }
                    }
                    maskColor={
                      isDark ? "rgba(15, 23, 42, 0.75)" : "rgba(241, 245, 249, 0.75)"
                    }
                  />

                  <Panel position="top-left" className="space-y-1.5">
                    <div className="rounded-lg border border-gray-200 bg-white/90 px-3 py-2 shadow-sm backdrop-blur dark:border-gray-600 dark:bg-gray-900/95">
                      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
                        {t.explorer.nodeTypes}
                      </p>
                      <div className="flex flex-wrap gap-x-3 gap-y-1">
                        {legend.map((l) => (
                          <span
                            key={l.type}
                            className="flex items-center gap-1.5 text-[11px] text-gray-500 dark:text-gray-400"
                          >
                            <span
                              className="inline-block h-2.5 w-2.5 rounded-sm"
                              style={{ backgroundColor: l.color }}
                            />
                            {l.type}
                          </span>
                        ))}
                      </div>
                      <p className="mb-1.5 mt-2 text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
                        {t.explorer.edgeTypes}
                      </p>
                      <div className="flex flex-wrap gap-x-3 gap-y-1">
                        {edgeLegend.map((l) => (
                          <span
                            key={l.type}
                            className="flex items-center gap-1.5 text-[11px] text-gray-500 dark:text-gray-400"
                          >
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
            <div className="flex min-h-[500px] flex-1 items-center justify-center rounded-xl border border-gray-200 bg-gray-50 text-gray-500 dark:border-gray-700 dark:bg-slate-900 dark:text-gray-400">
              <div className="text-center">
                <Network size={48} className="mx-auto mb-3 opacity-30 dark:opacity-40" aria-hidden />
                <p className="text-sm">{t.explorer.emptyHint}</p>
              </div>
            </div>
          )}
        </div>

        {selectedApiNode ? (
          <aside className="w-full shrink-0 rounded-xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900 lg:w-80">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 dark:text-gray-500">
              {t.explorer.panelTitle}
            </h3>
            <div className="mt-3 flex items-start justify-between gap-2">
              <p className="break-all text-sm font-semibold text-gray-900 dark:text-gray-100">{selectedApiNode.name}</p>
              <span
                className="shrink-0 rounded-md px-2 py-0.5 text-[10px] font-medium"
                style={{
                  backgroundColor:
                    paletteForTheme(isDark)[normalizeGraphType(selectedApiNode.type)]?.bg ?? "#f1f5f9",
                  color: paletteForTheme(isDark)[normalizeGraphType(selectedApiNode.type)]?.text ?? "#334155",
                  border: `1px solid ${paletteForTheme(isDark)[normalizeGraphType(selectedApiNode.type)]?.border ?? "#64748b"}`,
                }}
              >
                {selectedApiNode.type}
              </span>
            </div>

            {selectedApiNode.file ? (
              <p className="mt-2 break-all text-xs text-gray-600 dark:text-gray-400">{selectedApiNode.file}</p>
            ) : null}

            <p className="mt-2 text-xs text-gray-700 dark:text-gray-300">
              <span className="font-medium text-gray-500 dark:text-gray-400">{t.explorer.panelLineRange}: </span>
              {selectedApiNode.line != null
                ? selectedApiNode.end_line != null && selectedApiNode.end_line !== selectedApiNode.line
                  ? `${selectedApiNode.line}–${selectedApiNode.end_line}`
                  : String(selectedApiNode.line)
                : "—"}
            </p>

            {selectedApiNode.signature ? (
              <div className="mt-3">
                <p className="text-[11px] font-medium text-gray-500 dark:text-gray-400">{t.explorer.panelSignature}</p>
                <pre className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap break-all rounded-md bg-gray-50 p-2 text-[11px] text-gray-800 dark:bg-gray-800 dark:text-gray-200">
                  {selectedApiNode.signature}
                </pre>
              </div>
            ) : null}

            {selectedApiNode.docstring ? (
              <div className="mt-3">
                <p className="text-[11px] font-medium text-gray-500 dark:text-gray-400">{t.explorer.panelDocstring}</p>
                <p className="mt-1 text-xs leading-relaxed text-gray-700 dark:text-gray-300">
                  {truncateDoc(selectedApiNode.docstring)}
                </p>
              </div>
            ) : null}

            <div className="mt-4 flex flex-col gap-2">
              <button
                type="button"
                disabled={expandMutation.isPending}
                onClick={() => handleExpandNeighbors(selectedApiNode.name, 100)}
                className="inline-flex items-center justify-center rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-900 transition-colors hover:bg-emerald-100 disabled:opacity-50 dark:border-emerald-900 dark:bg-emerald-950/80 dark:text-emerald-100 dark:hover:bg-emerald-900"
              >
                {t.explorer.expandAllNeighbors}
              </button>
              <Link
                to={
                  selectedApiNode.name
                    ? `/search?mode=wiki&q=${encodeURIComponent(selectedApiNode.name)}`
                    : "/search?mode=wiki"
                }
                className="inline-flex items-center justify-center rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs font-medium text-sky-900 hover:bg-sky-100 dark:border-sky-800 dark:bg-sky-950/80 dark:text-sky-100 dark:hover:bg-sky-900"
              >
                {t.explorer.openInWiki}
              </Link>
              <Link
                to={selectedApiNode.name ? `/search?q=${encodeURIComponent(selectedApiNode.name)}` : "/search"}
                className="inline-flex items-center justify-center rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-800 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-700"
              >
                <Search size={14} className="mr-1.5 inline" />
                {t.explorer.searchRelated}
              </Link>
            </div>

            <p className="mt-4 text-[10px] text-gray-400 dark:text-gray-500">{t.explorer.doubleClickHint}</p>
          </aside>
        ) : null}
      </div>
    </div>
  );
}
