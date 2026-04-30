import { useMemo, useCallback, useState, useEffect } from "react";
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

function useDarkMode(): boolean {
  const [isDark, setIsDark] = useState(() =>
    document.documentElement.classList.contains("dark"),
  );
  useEffect(() => {
    const el = document.documentElement;
    const observer = new MutationObserver(() => {
      setIsDark(el.classList.contains("dark"));
    });
    observer.observe(el, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);
  return isDark;
}

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
  /** When true, shows loading UI (e.g. parent React Query initial fetch). */
  isLoading?: boolean;
  /** When set, shows error UI instead of the graph. */
  error?: unknown;
}

export default function WikiKnowledgeGraph({
  domains,
  domainEdges,
  onNodeClick,
  isLoading = false,
  error = null,
}: Props) {
  const isDark = useDarkMode();

  const nodes: Node[] = useMemo(() => {
    const cols = Math.max(Math.ceil(Math.sqrt(domains.length)), 1);
    return domains.map((d, i) => ({
      id: d.id,
      position: { x: (i % cols) * 220, y: Math.floor(i / cols) * 160 },
      data: { label: d.label },
      style: {
        background: isDark ? "#1e293b" : "#e0f2fe",
        border: `1px solid ${isDark ? "#475569" : "#7dd3fc"}`,
        borderRadius: "8px",
        padding: "10px 14px",
        fontSize: "12px",
        fontWeight: 600,
        color: isDark ? "#e2e8f0" : "#0c4a6e",
        cursor: "pointer",
      },
    }));
  }, [domains, isDark]);

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

  if (isLoading) {
    return (
      <div className="flex h-48 items-center justify-center text-sm text-gray-400 dark:text-gray-500">
        加载中...
      </div>
    );
  }
  if (error != null) {
    const message = error instanceof Error ? error.message : String(error);
    return (
      <div className="flex h-48 items-center justify-center text-sm text-red-400 dark:text-red-400">
        加载失败: {message}
      </div>
    );
  }

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
