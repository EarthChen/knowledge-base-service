import { useCallback, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
} from "@xyflow/react";
import dagre from "@dagrejs/dagre";
import "@xyflow/react/dist/style.css";

const NODE_W = 180;
const NODE_H = 44;

const TYPE_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  Function: { bg: "#ecfdf5", border: "#10b981", text: "#065f46" },
  Class: { bg: "#e0f2fe", border: "#0ea5e9", text: "#0c4a6e" },
  Module: { bg: "#faf5ff", border: "#a855f7", text: "#581c87" },
  root: { bg: "#fef3c7", border: "#f59e0b", text: "#78350f" },
};

function getColor(type: string, isRoot: boolean) {
  if (isRoot) return TYPE_COLORS.root;
  return TYPE_COLORS[type] || TYPE_COLORS.Function;
}

interface ResultItem {
  name: string;
  file?: string;
  line?: number;
  type?: string;
  fqn?: string;
  [key: string]: unknown;
}

interface EdgeItem {
  source: string;
  target: string;
}

interface Props {
  queryType: string;
  rootName: string;
  results: ResultItem[];
  direction?: string;
  edges?: EdgeItem[];
  onNodeDoubleClick?: (name: string) => void;
}

function layoutDagre(
  nodes: Node[],
  edges: Edge[],
  dir: "TB" | "LR" = "TB",
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: dir, nodesep: 30, ranksep: 50 });

  for (const n of nodes) {
    g.setNode(n.id, { width: NODE_W, height: NODE_H });
  }
  for (const e of edges) {
    g.setEdge(e.source, e.target);
  }

  dagre.layout(g);

  const laid = nodes.map((n) => {
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 } };
  });

  return { nodes: laid, edges };
}

function truncName(name: string, maxLen = 28): string {
  if (name.length <= maxLen) return name;
  return name.slice(0, maxLen - 1) + "…";
}

function makeNodeStyle(c: { bg: string; border: string; text: string }, isRoot: boolean) {
  return {
    background: c.bg,
    border: `${isRoot ? 2 : 1.5}px solid ${c.border}`,
    color: c.text,
    borderRadius: 8,
    padding: "6px 10px",
    fontWeight: isRoot ? 600 : 400,
    fontSize: 12,
    width: NODE_W,
    textAlign: "center" as const,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap" as const,
  };
}

function buildNodesAndEdges(
  queryType: string,
  rootName: string,
  results: ResultItem[],
  direction?: string,
  edgeList?: EdgeItem[],
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const seen = new Set<string>();

  const simpleRoot = rootName.includes("#")
    ? rootName.split("#").pop()!
    : rootName.includes(".")
      ? rootName.split(".").pop()!
      : rootName;

  const rootId = `root_${simpleRoot}`;
  const rc = TYPE_COLORS.root;
  nodes.push({
    id: rootId,
    data: { label: truncName(simpleRoot), entityType: "root", fqn: rootName },
    position: { x: 0, y: 0 },
    style: makeNodeStyle(rc, true),
  });
  seen.add(rootId);

  const deduped: ResultItem[] = [];
  const dedupKeys = new Set<string>();
  for (const r of results) {
    const key = `${r.name}:${r.line || 0}`;
    if (!dedupKeys.has(key)) {
      dedupKeys.add(key);
      deduped.push(r);
    }
  }

  const nodeIdMap = new Map<string, string>();
  nodeIdMap.set(`${simpleRoot}:0`, rootId);

  for (const result of results) {
    const key = `${result.name}:${result.line || 0}`;
    if (nodeIdMap.has(key)) continue;
    const origKey = key;

    if (result.name === simpleRoot && !nodeIdMap.has(key)) {
      nodeIdMap.set(key, rootId);
      continue;
    }
    nodeIdMap.set(origKey, key);
  }

  for (const item of deduped) {
    const nodeId = `${item.name}:${item.line || 0}`;
    if (nodeId === rootId || (item.name === simpleRoot)) continue;
    if (seen.has(nodeId)) continue;
    seen.add(nodeId);

    const entityType = item.type || "Function";
    const c = getColor(entityType, false);
    nodes.push({
      id: nodeId,
      data: { label: truncName(item.name), entityType, fqn: item.fqn || item.name },
      position: { x: 0, y: 0 },
      style: makeNodeStyle(c, false),
    });
  }

  if (edgeList && edgeList.length > 0) {
    const edgeSeen = new Set<string>();
    for (const e of edgeList) {
      let srcId = e.source;
      let tgtId = e.target;

      if (srcId.split(":")[0] === simpleRoot) srcId = rootId;
      if (tgtId.split(":")[0] === simpleRoot) tgtId = rootId;

      const srcExists = nodes.some((n) => n.id === srcId);
      const tgtExists = nodes.some((n) => n.id === tgtId);
      if (!srcExists || !tgtExists) continue;

      const ek = `${srcId}->${tgtId}`;
      if (edgeSeen.has(ek)) continue;
      edgeSeen.add(ek);

      edges.push({
        id: ek,
        source: srcId,
        target: tgtId,
        animated: true,
        style: { stroke: "#64748b", strokeWidth: 1.5 },
      });
    }
  } else {
    for (const item of deduped) {
      const nodeId = `${item.name}:${item.line || 0}`;
      const actualNodeId = item.name === simpleRoot ? rootId : nodeId;
      if (actualNodeId === rootId) continue;

      const isUpstream = direction === "upstream";
      const isInheritance = queryType === "inheritance_tree";

      let src: string, tgt: string;
      if (isUpstream || isInheritance) {
        src = actualNodeId;
        tgt = rootId;
      } else {
        src = rootId;
        tgt = actualNodeId;
      }

      const edgeId = `${src}->${tgt}`;
      if (!seen.has(edgeId)) {
        seen.add(edgeId);
        edges.push({
          id: edgeId,
          source: src,
          target: tgt,
          animated: true,
          style: { stroke: "#64748b", strokeWidth: 1.5 },
        });
      }
    }
  }

  return layoutDagre(nodes, edges, "TB");
}

export default function GraphFlowChart({ queryType, rootName, results, direction, edges: edgeList, onNodeDoubleClick }: Props) {
  const { nodes: initNodes, edges: initEdges } = useMemo(
    () => buildNodesAndEdges(queryType, rootName, results, direction, edgeList),
    [queryType, rootName, results, direction, edgeList],
  );

  const [nodes, , onNodesChange] = useNodesState(initNodes);
  const [edges, , onEdgesChange] = useEdgesState(initEdges);

  const onInit = useCallback((instance: { fitView: () => void }) => {
    setTimeout(() => instance.fitView(), 100);
  }, []);

  const handleNodeDblClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      const fqn = String(node.data?.fqn || "");
      const name = fqn || String(node.data?.label || "").replace("…", "");
      if (name && onNodeDoubleClick) {
        onNodeDoubleClick(name);
      }
    },
    [onNodeDoubleClick],
  );

  if (results.length === 0) return null;

  return (
    <div className="h-[500px] rounded-xl border border-gray-200 bg-white">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeDoubleClick={handleNodeDblClick}
        onInit={onInit}
        fitView
        proOptions={{ hideAttribution: true }}
        minZoom={0.2}
        maxZoom={2}
      >
        <Background color="#e2e8f0" gap={20} />
        <Controls
          showInteractive={false}
          style={{ background: "#ffffff", borderColor: "#cbd5e1" }}
        />
        <MiniMap
          nodeColor={(n) => {
            const c = getColor(String(n.data?.entityType || "Function"), n.id.startsWith("root_"));
            return c.border;
          }}
          maskColor="rgba(255,255,255,0.7)"
          style={{ background: "#f8fafc", borderColor: "#cbd5e1" }}
        />
      </ReactFlow>
    </div>
  );
}
