import { useMemo, useCallback } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

interface DomainInfo {
  id: string;
  label: string;
  children: string[];
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
}

export default function WikiKnowledgeGraph({ domains, domainEdges, onNodeClick }: Props) {
  const nodes: Node[] = useMemo(() => {
    const cols = Math.max(Math.ceil(Math.sqrt(domains.length)), 1);
    return domains.map((d, i) => ({
      id: d.id,
      position: { x: (i % cols) * 220, y: Math.floor(i / cols) * 160 },
      data: { label: d.label },
      style: {
        background: "#e0f2fe",
        border: "1px solid #7dd3fc",
        borderRadius: "8px",
        padding: "10px 14px",
        fontSize: "12px",
        fontWeight: 600,
        cursor: "pointer",
      },
    }));
  }, [domains]);

  const edges: Edge[] = useMemo(
    () =>
      domainEdges.map((e, i) => ({
        id: `edge-${i}`,
        source: e.source,
        target: e.target,
        label: e.label,
        animated: true,
        style: { stroke: "#94a3b8" },
        labelStyle: { fontSize: 10, fill: "#64748b" },
      })),
    [domainEdges],
  );

  const handleNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => onNodeClick(node.id),
    [onNodeClick],
  );

  if (domains.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center rounded-lg border border-gray-200 text-sm text-gray-400 dark:border-gray-700">
        暂无域关系数据
      </div>
    );
  }

  return (
    <div className="h-[500px] w-full rounded-lg border border-gray-200 dark:border-gray-700">
      <ReactFlow
        nodes={nodes}
        edges={edges}
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
