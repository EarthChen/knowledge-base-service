import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

type FlowNode = {
  uid: string;
  title: string;
  description?: string;
  type?: string;
};

type FlowEdge = {
  source: string;
  target: string;
  label?: string;
};

export function useBusinessFlows(businessId: string) {
  return useQuery({
    queryKey: ["wiki", "business-flows", businessId],
    queryFn: () =>
      api<{ nodes: FlowNode[]; edges: FlowEdge[] }>(
        `/wiki/flows?business_id=${encodeURIComponent(businessId)}`,
      ),
    enabled: !!businessId.trim(),
  });
}
