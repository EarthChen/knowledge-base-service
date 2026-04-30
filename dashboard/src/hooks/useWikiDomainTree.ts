import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export interface TopicTreeNode {
  name: string;
  page_type: string;
  path: string;
  children: TopicTreeNode[];
  review_status?: string;
}

interface TopicTreeResponse {
  tree: TopicTreeNode[];
}

export function useWikiTopicTree(businessId: string) {
  return useQuery<TopicTreeResponse>({
    queryKey: ["wiki", "topic-tree", businessId],
    queryFn: () => api(`/wiki/topic-tree?business_id=${encodeURIComponent(businessId)}`),
    enabled: !!businessId,
    staleTime: 30_000,
  });
}

interface DomainTreeResponse {
  tree: TopicTreeNode[];
  review_status: Record<string, string>;
}

export function useWikiDomainTree(businessId: string) {
  return useQuery<DomainTreeResponse>({
    queryKey: ["wiki", "domain-tree", businessId],
    queryFn: () => api(`/wiki/domain-tree?business_id=${encodeURIComponent(businessId)}`),
    enabled: !!businessId,
    staleTime: 30_000,
  });
}
