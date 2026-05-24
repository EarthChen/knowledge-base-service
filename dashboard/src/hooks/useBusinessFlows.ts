import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";

export type FlowNodeType = "business_flow" | "flow_step" | string;

export type FlowNode = {
  uid: string;
  title: string;
  description?: string;
  type?: FlowNodeType;
};

export type FlowEdge = {
  source: string;
  target: string;
  label?: string;
};

export type BusinessFlowsData = {
  nodes: FlowNode[];
  edges: FlowEdge[];
};

export function useBusinessFlows(businessId: string) {
  return useQuery<BusinessFlowsData>({
    queryKey: queryKeys.wiki.businessFlows(businessId),
    queryFn: () =>
      api<BusinessFlowsData>(
        `/wiki/flows?business_id=${encodeURIComponent(businessId)}`,
      ),
    enabled: !!businessId.trim(),
  });
}
