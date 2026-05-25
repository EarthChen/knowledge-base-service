import {
  useState,
  useCallback,
  useMemo,
  useRef,
  useEffect,
  type MutableRefObject,
} from "react";
import { useSearchParams } from "react-router-dom";
import { useNodesState, useEdgesState, type NodeMouseHandler, type Node, type Edge } from "@xyflow/react";
import {
  useGraphExplore,
  useGraphExpand,
  useBlastRadius,
  useGraphCommunities,
  useRepositories,
} from "../../api/hooks";
import { getCurrentBusiness } from "../../api/client";
import { useWikiPathForSourceEntity } from "../../hooks/useWikiPathForSourceEntity";
import { useI18n } from "../../i18n/context";
import type {
  GraphExploreResponse,
  GraphNode as ApiNode,
  GraphEdge as ApiEdge,
  CommunityInfo,
} from "../../api/types";
import {
  applyNodeStyles,
  buildFlowEdges,
  computeDagrePositions,
  DEFAULT_VISIBILITY,
  EDGE_COLORS,
  INITIAL_NODE_LIMIT,
  MAX_GRAPH_NODES,
  mergeGraphEdges,
  normalizeGraphType,
  paletteForTheme,
  type NodeTypeKey,
} from "./graphLayout";

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

function ingestExploreResult(
  data: GraphExploreResponse,
  selectId: string | null,
  opts: {
    setInitialSliceHint: (v: boolean) => void;
    setExpandHistory: (v: string[][]) => void;
    setSelectedNodeId: (v: string | null) => void;
    apiNodesRef: MutableRefObject<Map<string, ApiNode>>;
    edgesRef: MutableRefObject<ApiEdge[]>;
    applyGraphLayout: () => void;
    expandReset: () => void;
  },
) {
  const {
    setInitialSliceHint,
    setExpandHistory,
    setSelectedNodeId,
    apiNodesRef,
    edgesRef,
    applyGraphLayout,
    expandReset,
  } = opts;
  expandReset();
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
  setSelectedNodeId(selectId);
}

export function useGraphExplorerState() {
  const [searchParams] = useSearchParams();
  const [searchName, setSearchName] = useState(() => searchParams.get("q") ?? "");
  const [depth, setDepth] = useState(2);
  const [limit, setLimit] = useState(100);
  const depthRef = useRef(depth);
  const limitRef = useRef(limit);
  depthRef.current = depth;
  limitRef.current = limit;
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
  const [graphSnapshot, setGraphSnapshot] = useState<{ nodes: ApiNode[]; edges: ApiEdge[] }>({
    nodes: [],
    edges: [],
  });

  const apiNodesRef = useRef<Map<string, ApiNode>>(new Map());
  const edgesRef = useRef<ApiEdge[]>([]);
  const visibleNodeIdsRef = useRef<Set<string>>(new Set());

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
    setGraphSnapshot({
      nodes: [...apiNodesRef.current.values()],
      edges: [...edgesRef.current],
    });
  }, []);

  const highlightSet = useMemo(
    () => (communityHighlight.size ? communityHighlight : undefined),
    [communityHighlight],
  );

  const dagrePositions = useMemo(
    () => computeDagrePositions(graphSnapshot.nodes, graphSnapshot.edges),
    [graphSnapshot.nodes, graphSnapshot.edges],
  );

  const styledFlowNodes = useMemo(
    () => applyNodeStyles(graphSnapshot.nodes, dagrePositions, isDark, highlightSet),
    [graphSnapshot.nodes, dagrePositions, isDark, highlightSet],
  );

  const handleExplore = useCallback(
    (name: string) => {
      mutation.mutate(
        { name: name.trim(), depth, limit },
        {
          onSuccess: (data) => {
            ingestExploreResult(data, null, {
              setInitialSliceHint,
              setExpandHistory,
              setSelectedNodeId,
              apiNodesRef,
              edgesRef,
              applyGraphLayout,
              expandReset: () => expandMutation.reset(),
            });
          },
        },
      );
    },
    [depth, limit, mutation, expandMutation, applyGraphLayout],
  );

  const nodeDeepLinkRef = useRef<string | null>(null);
  const nodeParam = searchParams.get("node");
  useEffect(() => {
    const n = (nodeParam ?? "").trim();
    if (!n) {
      nodeDeepLinkRef.current = null;
      return;
    }
    if (nodeDeepLinkRef.current === n) return;
    nodeDeepLinkRef.current = n;
    mutation.mutate(
      { name: "", center_uid: n, depth: depthRef.current, limit: limitRef.current },
      {
        onSuccess: (data) => {
          ingestExploreResult(data, n, {
            setInitialSliceHint,
            setExpandHistory,
            setSelectedNodeId,
            apiNodesRef,
            edgesRef,
            applyGraphLayout,
            expandReset: () => expandMutation.reset(),
          });
        },
      },
    );
  }, [nodeParam, mutation, expandMutation, applyGraphLayout]);

  useEffect(() => {
    if (graphSnapshot.nodes.length === 0) {
      setNodes([]);
      setEdges([]);
      return;
    }
    const flowNodes = styledFlowNodes.map((n) => {
      const nt = normalizeGraphType((n.data?.type as string) || "");
      let vis = true;
      if (nt !== "Unknown") vis = typeVisible[nt as NodeTypeKey];
      return { ...n, hidden: !vis };
    });
    const nodeIds = new Set(styledFlowNodes.map((n) => n.id));
    visibleNodeIdsRef.current = nodeIds;
    setNodes(flowNodes);
    setEdges(buildFlowEdges(graphSnapshot.edges, nodeIds, showEdgeLabels, isDark));
  }, [graphSnapshot, styledFlowNodes, typeVisible, showEdgeLabels, isDark, setNodes, setEdges]);

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
    (nodeUid: string, expandLimit: number) => {
      const uid = nodeUid.trim();
      if (!uid) return;
      if (apiNodesRef.current.size >= MAX_GRAPH_NODES) return;
      const selectedNode = apiNodesRef.current.get(uid);
      if (!selectedNode) return;
      const existingUids = [...apiNodesRef.current.keys()];
      expandMutation.mutate(
        {
          node_name: selectedNode.name,
          center_uid: uid,
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

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      if (searchName.trim()) handleExplore(searchName.trim());
    },
    [searchName, handleExplore],
  );

  const onNodeDoubleClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      if (node.id && !expandMutation.isPending) {
        handleExpandNeighbors(node.id, 20);
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

  const selectedApiNode = selectedNodeId ? apiNodesRef.current.get(selectedNodeId) : undefined;
  const businessId = getCurrentBusiness();
  const wikiForEntity = useWikiPathForSourceEntity(businessId, selectedNodeId, {
    enabled: Boolean(selectedNodeId?.trim()),
  });

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

  return {
    t,
    isDark,
    searchName,
    setSearchName,
    depth,
    setDepth,
    limit,
    setLimit,
    handleSubmit,
    mutation,
    initialSliceHint,
    expandMutation,
    expandHistory,
    handleUndoExpand,
    blastNamesInput,
    setBlastNamesInput,
    blastDepth,
    setBlastDepth,
    blastRepo,
    setBlastRepo,
    blastMutation,
    handleBlastRadius,
    communityRepo,
    setCommunityRepo,
    communityMinSize,
    setCommunityMinSize,
    communitiesMutation,
    handleLoadCommunities,
    handleCommunityClick,
    selectedCommunityKey,
    reposQuery,
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onNodeClick,
    onNodeDoubleClick,
    containerRef,
    typeVisible,
    toggleType,
    showEdgeLabels,
    setShowEdgeLabels,
    legend,
    edgeLegend,
    selectedApiNode,
    businessId,
    wikiForEntity,
    handleExpandNeighbors,
  };
}
