/* eslint-disable react-refresh/only-export-components -- layoutFlowWithDagre exported for unit tests */
import { useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeProps,
  ReactFlowProvider,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";
import { useBusinessFlows } from "../../hooks/useBusinessFlows";
import { useI18n } from "../../i18n/context";

type Props = { businessId: string };

const BUSINESS_FLOW_SIZE = { width: 220, height: 90 };
const FLOW_STEP_SIZE = { width: 160, height: 60 };

export function layoutFlowWithDagre(
  nodes: Node[],
  edges: Edge[],
  direction: "TB" | "LR" = "TB",
): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: direction, nodesep: 50, ranksep: 70 });

  for (const n of nodes) {
    const isFlow = n.type === "businessFlow";
    const size = isFlow ? BUSINESS_FLOW_SIZE : FLOW_STEP_SIZE;
    g.setNode(n.id, { width: size.width, height: size.height });
  }
  for (const e of edges) {
    g.setEdge(e.source, e.target);
  }

  dagre.layout(g);

  return nodes.map((n) => {
    const isFlow = n.type === "businessFlow";
    const size = isFlow ? BUSINESS_FLOW_SIZE : FLOW_STEP_SIZE;
    const pos = g.node(n.id);
    return {
      ...n,
      position: { x: pos.x - size.width / 2, y: pos.y - size.height / 2 },
    };
  });
}

interface FlowNodeData {
  label: string;
  nodeType: string;
}

function BusinessFlowNode({ data }: NodeProps) {
  const nodeData = data as unknown as FlowNodeData;
  return (
    <div
      style={{
        position: "relative",
        background: "#dbeafe",
        border: "2px solid #3b82f6",
        borderRadius: "10px",
        padding: "12px 16px",
        minWidth: "180px",
        boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
      }}
    >
      <Handle type="target" position={Position.Top} style={{ visibility: "hidden" }} />
      <div style={{ fontWeight: 700, fontSize: "13px", color: "#1e40af" }}>{nodeData.label}</div>
      <div style={{ fontSize: "10px", color: "#3b82f6", marginTop: 4, textTransform: "uppercase" }}>
        Business Flow
      </div>
      <Handle type="source" position={Position.Bottom} style={{ visibility: "hidden" }} />
    </div>
  );
}

function FlowStepNode({ data }: NodeProps) {
  const nodeData = data as unknown as FlowNodeData;
  return (
    <div
      style={{
        position: "relative",
        background: "#fef3c7",
        border: "1.5px solid #f59e0b",
        borderRadius: "8px",
        padding: "8px 12px",
        minWidth: "120px",
      }}
    >
      <Handle type="target" position={Position.Top} style={{ visibility: "hidden" }} />
      <div style={{ fontWeight: 600, fontSize: "12px", color: "#92400e" }}>{nodeData.label}</div>
      <div style={{ fontSize: "9px", color: "#d97706", marginTop: 2, textTransform: "uppercase" }}>
        Step
      </div>
      <Handle type="source" position={Position.Bottom} style={{ visibility: "hidden" }} />
    </div>
  );
}

const nodeTypes = {
  businessFlow: BusinessFlowNode,
  flowStep: FlowStepNode,
};

function FlowInner({ businessId }: Props) {
  const { t } = useI18n();
  const { data, isLoading, error } = useBusinessFlows(businessId);

  const { nodes, edges } = useMemo(() => {
    if (!data?.nodes?.length) return { nodes: [] as Node[], edges: [] as Edge[] };

    const rawNodes: Node[] = data.nodes.map((n) => {
      const isFlowStep = n.type === "flow_step";
      return {
        id: n.uid,
        type: isFlowStep ? "flowStep" : "businessFlow",
        data: { label: n.title || n.uid, nodeType: n.type ?? "business_flow" },
        position: { x: 0, y: 0 },
      };
    });

    const rawEdges: Edge[] = (data.edges ?? []).map((e, i) => ({
      id: `edge-${i}`,
      source: e.source,
      target: e.target,
      label: e.label,
      animated: true,
      style: { stroke: "#6366f1" },
      labelStyle: { fontSize: 10, fill: "#6366f1" },
    }));

    return {
      nodes: layoutFlowWithDagre(rawNodes, rawEdges),
      edges: rawEdges,
    };
  }, [data]);

  if (isLoading) {
    return (
      <div
        data-testid="flow-graph-container"
        className="flex h-64 items-center justify-center text-sm text-gray-400"
      >
        {t.wiki.business_flow.loading}
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
        {t.wiki.business_flow.no_flows}
      </div>
    );
  }

  return (
    <div
      data-testid="flow-graph-container"
      className="h-[500px] w-full rounded-lg border border-gray-200 dark:border-gray-700"
    >
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView>
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
