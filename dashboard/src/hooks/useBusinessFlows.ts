import { useQuery } from "@tanstack/react-query";

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
    queryFn: async () => {
      const resp = await fetch(`/api/v1/wiki/flows?business_id=${encodeURIComponent(businessId)}`);
      if (!resp.ok) return { nodes: [], edges: [] };
      return resp.json() as Promise<{ nodes: FlowNode[]; edges: FlowEdge[] }>;
    },
    enabled: !!businessId.trim(),
  });
}
