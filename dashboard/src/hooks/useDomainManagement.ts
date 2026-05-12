import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";

export interface DomainAnchor {
  slug: string;
  display_name: string;
  module_count: number;
}

export interface PinnedModule {
  module_name: string;
  domain_slug: string;
}

export function useDomainList(businessId: string) {
  return useQuery({
    queryKey: ["domains", businessId],
    queryFn: async (): Promise<DomainAnchor[]> => {
      const data = await api<{ domains?: DomainAnchor[] }>(
        `/wiki/${encodeURIComponent(businessId)}/domains`,
      );
      return data.domains ?? [];
    },
    enabled: !!businessId,
  });
}

export function usePinnedModules(businessId: string) {
  return useQuery({
    queryKey: ["pinned-modules", businessId],
    queryFn: async (): Promise<PinnedModule[]> => {
      const data = await api<{ pinned_modules?: PinnedModule[] }>(
        `/wiki/${encodeURIComponent(businessId)}/domains/pinned-modules`,
      );
      return data.pinned_modules ?? [];
    },
    enabled: !!businessId,
  });
}

export function useUpsertDomain(businessId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ slug, displayName }: { slug: string; displayName: string }) => {
      await api(`/wiki/${encodeURIComponent(businessId)}/domains/${encodeURIComponent(slug)}`, {
        method: "PUT",
        body: JSON.stringify({ display_name: displayName }),
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["domains", businessId] });
    },
  });
}

export function useDeleteDomain(businessId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (slug: string) => {
      await api(`/wiki/${encodeURIComponent(businessId)}/domains/${encodeURIComponent(slug)}`, {
        method: "DELETE",
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["domains", businessId] });
      void qc.invalidateQueries({ queryKey: ["pinned-modules", businessId] });
    },
  });
}

export function usePinModule(businessId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ moduleName, domainSlug }: { moduleName: string; domainSlug: string }) => {
      await api(`/wiki/${encodeURIComponent(businessId)}/domains/pin-module`, {
        method: "POST",
        body: JSON.stringify({ module_name: moduleName, domain_slug: domainSlug }),
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["pinned-modules", businessId] });
      void qc.invalidateQueries({ queryKey: ["domains", businessId] });
    },
  });
}

export function useUnpinModule(businessId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (moduleName: string) => {
      await api(`/wiki/${encodeURIComponent(businessId)}/domains/unpin-module`, {
        method: "POST",
        body: JSON.stringify({ module_name: moduleName }),
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["pinned-modules", businessId] });
      void qc.invalidateQueries({ queryKey: ["domains", businessId] });
    },
  });
}
