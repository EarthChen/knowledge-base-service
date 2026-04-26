import { useMemo } from "react";
import { ReactFlow, Background, Controls, type Node, type Edge, ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useBusinessFlows } from "../../hooks/useBusinessFlows";
import { useI18n } from "../../i18n/context";

type Props = { businessId: string };

function FlowInner({ businessId }: Props) {
  const { t } = useI18n();
  const { data, isLoading, error } = useBusinessFlows(businessId);

  const nodes: Node[] = useMemo(() => {
    if (!data?.nodes) return [];
    return data.nodes.map((n, i) => ({
      id: n.uid,
      data: { label: n.title || n.uid },
      position: { x: (i % 4) * 250, y: Math.floor(i / 4) * 150 },
      type: "default",
    }));
  }, [data?.nodes]);

  const edges: Edge[] = useMemo(() => {
    if (!data?.edges) return [];
    return data.edges.map((e, i) => ({
      id: `edge-${i}`,
      source: e.source,
      target: e.target,
      label: e.label,
      animated: true,
    }));
  }, [data?.edges]);

  if (isLoading) {
    return (
      <div
        data-testid="flow-graph-container"
        className="flex h-64 items-center justify-center text-sm text-gray-400"
      >
        Loading flows...
      </div>
    );
  }

  if (error) {
    const message = error instanceof Error ? error.message : String(error);
    return (
      <div
        data-testid="flow-graph-container"
        className="flex h-64 items-center justify-center text-sm text-red-600 dark:text-red-400"
      >
        {t.wiki.flowsLoadFailed.replace("{message}", message)}
      </div>
    );
  }

  if (!nodes.length) {
    return (
      <div
        data-testid="flow-graph-container"
        className="flex h-64 items-center justify-center text-sm text-gray-400"
      >
        No business flows found
      </div>
    );
  }

  return (
    <div data-testid="flow-graph-container" className="h-[500px] w-full rounded-lg border border-gray-200 dark:border-gray-700">
      <ReactFlow nodes={nodes} edges={edges} fitView>
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  );
}

export default function WikiBusinessFlowGraph({ businessId }: Props) {
  return (
    <ReactFlowProvider>
      <FlowInner businessId={businessId} />
    </ReactFlowProvider>
  );
}
