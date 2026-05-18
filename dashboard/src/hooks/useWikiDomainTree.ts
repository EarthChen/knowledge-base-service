import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { queryKeys } from "../api/queryKeys";

export interface TopicTreeNode {
  uid?: string;
  name: string;
  label?: string;
  page_type: string;
  path: string;
  children: TopicTreeNode[];
  review_status?: string;
  description?: string;
  module_count?: number;
  quality_score?: number;
}

interface TopicTreeResponse {
  tree: TopicTreeNode[];
}

export function useWikiTopicTree(businessId: string) {
  return useQuery<TopicTreeResponse>({
    queryKey: queryKeys.wiki.topicTree(businessId),
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
    queryKey: queryKeys.wiki.domainTree(businessId),
    queryFn: () => api(`/wiki/domain-tree?business_id=${encodeURIComponent(businessId)}`),
    enabled: !!businessId,
    staleTime: 30_000,
  });
}

interface DomainEdge {
  source: string;
  target: string;
  label: string;
}

interface DomainEdgesResponse {
  edges: DomainEdge[];
}

export function useWikiDomainEdges(businessId: string) {
  return useQuery<DomainEdgesResponse>({
    queryKey: queryKeys.wiki.domainEdges(businessId),
    queryFn: () => api(`/wiki/domain-edges?business_id=${encodeURIComponent(businessId)}`),
    enabled: !!businessId,
    staleTime: 60_000,
  });
}
