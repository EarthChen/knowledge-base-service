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

const NODE_W = 220;
const NODE_H = 50;

const TYPE_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  Function: { bg: "#064e3b", border: "#10b981", text: "#6ee7b7" },
  Class: { bg: "#0c4a6e", border: "#0ea5e9", text: "#7dd3fc" },
  Module: { bg: "#3b0764", border: "#a855f7", text: "#d8b4fe" },
  root: { bg: "#78350f", border: "#f59e0b", text: "#fde68a" },
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
  [key: string]: unknown;
}

interface Props {
  queryType: string;
  rootName: string;
  results: ResultItem[];
  direction?: string;
}

function layoutDagre(
  nodes: Node[],
  edges: Edge[],
  dir: "TB" | "LR" = "TB",
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: dir, nodesep: 40, ranksep: 60 });

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

function buildNodesAndEdges(
  queryType: string,
  rootName: string,
  results: ResultItem[],
  direction?: string,
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const seen = new Set<string>();

  const rootId = `root_${rootName}`;
  nodes.push({
    id: rootId,
    data: {
      label: rootName,
      entityType: "root",
    },
    position: { x: 0, y: 0 },
    style: {
      background: TYPE_COLORS.root.bg,
      border: `2px solid ${TYPE_COLORS.root.border}`,
      color: TYPE_COLORS.root.text,
      borderRadius: 10,
      padding: "8px 14px",
      fontWeight: 600,
      fontSize: 13,
      minWidth: NODE_W,
      textAlign: "center" as const,
    },
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

  for (const item of deduped) {
    const nodeId = `${item.name}_${item.line || 0}`;
    if (!seen.has(nodeId)) {
      seen.add(nodeId);
      const entityType = item.type || "Function";
      const c = getColor(entityType, false);
      const shortFile = item.file
        ? item.file.replace(/.*\/src\/main\/java\//, "").replace(/.*\/src\//, "src/")
        : "";
      nodes.push({
        id: nodeId,
        data: {
          label: `${item.name}${shortFile ? `\n${shortFile}:${item.line || ""}` : ""}`,
          entityType,
        },
        position: { x: 0, y: 0 },
        style: {
          background: c.bg,
          border: `1.5px solid ${c.border}`,
          color: c.text,
          borderRadius: 8,
          padding: "6px 12px",
          fontSize: 11,
          minWidth: NODE_W,
          textAlign: "center" as const,
          whiteSpace: "pre-line" as const,
          lineHeight: "1.3",
        },
      });
    }

    const isUpstream = direction === "upstream";
    const isInheritance = queryType === "inheritance_tree";

    let src: string, tgt: string;
    if (isUpstream) {
      src = nodeId;
      tgt = rootId;
    } else if (isInheritance) {
      src = nodeId;
      tgt = rootId;
    } else {
      src = rootId;
      tgt = nodeId;
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

  const dagDir = direction === "upstream" ? "TB" : "TB";
  return layoutDagre(nodes, edges, dagDir);
}

export default function GraphFlowChart({ queryType, rootName, results, direction }: Props) {
  const { nodes: initNodes, edges: initEdges } = useMemo(
    () => buildNodesAndEdges(queryType, rootName, results, direction),
    [queryType, rootName, results, direction],
  );

  const [nodes, , onNodesChange] = useNodesState(initNodes);
  const [edges, , onEdgesChange] = useEdgesState(initEdges);

  const onInit = useCallback((instance: { fitView: () => void }) => {
    setTimeout(() => instance.fitView(), 100);
  }, []);

  if (results.length === 0) return null;

  return (
    <div className="h-[500px] rounded-xl border border-slate-800 bg-slate-900">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onInit={onInit}
        fitView
        proOptions={{ hideAttribution: true }}
        minZoom={0.3}
        maxZoom={2}
      >
        <Background color="#1e293b" gap={20} />
        <Controls
          showInteractive={false}
          style={{ background: "#1e293b", borderColor: "#334155" }}
        />
        <MiniMap
          nodeColor={(n) => {
            const c = getColor(String(n.data?.entityType || "Function"), n.id.startsWith("root_"));
            return c.border;
          }}
          maskColor="rgba(0,0,0,0.7)"
          style={{ background: "#0f172a", borderColor: "#334155" }}
        />
      </ReactFlow>
    </div>
  );
}
