import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useToast } from "../components/Toast";
import { getErrorMessage } from "../utils/errorUtils";
import { invalidateWikiQueriesForBusiness } from "./invalidateWikiQueries";

const BASE = "/wiki/domains/hierarchy";

function bq(businessId: string) {
  return `business_id=${encodeURIComponent(businessId)}`;
}

export function useDomainHierarchy(businessId: string) {
  const qc = useQueryClient();
  const { toast } = useToast();

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["domains", businessId] });
    void invalidateWikiQueriesForBusiness(qc, businessId);
  };

  const onError = (err: unknown) => {
    toast({ title: "Domain operation failed", description: getErrorMessage(err), variant: "destructive" });
  };

  const rename = useMutation({
    mutationFn: async ({
      uid,
      title,
      description,
    }: {
      uid: string;
      title?: string;
      description?: string;
    }) =>
      api(`${BASE}/${encodeURIComponent(uid)}?${bq(businessId)}`, {
        method: "PATCH",
        body: JSON.stringify({ title, description }),
      }),
    onSuccess: invalidate,
    onError,
  });

  const remove = useMutation({
    mutationFn: async ({
      uid,
      promoteChildren = true,
    }: {
      uid: string;
      promoteChildren?: boolean;
    }) =>
      api(
        `${BASE}/${encodeURIComponent(uid)}?${bq(businessId)}&promote_children=${promoteChildren}`,
        { method: "DELETE" },
      ),
    onSuccess: invalidate,
    onError,
  });

  const create = useMutation({
    mutationFn: async ({
      parentUid,
      title,
      description,
    }: {
      parentUid: string;
      title: string;
      description?: string;
    }) =>
      api(
        `${BASE}/${encodeURIComponent(parentUid)}/children?${bq(businessId)}`,
        {
          method: "POST",
          body: JSON.stringify({ title, description: description ?? "" }),
        },
      ),
    onSuccess: invalidate,
    onError,
  });

  const move = useMutation({
    mutationFn: async ({
      uid,
      targetParentUid,
    }: {
      uid: string;
      targetParentUid: string;
    }) =>
      api(`${BASE}/move?${bq(businessId)}`, {
        method: "POST",
        body: JSON.stringify({ uid, target_parent_uid: targetParentUid }),
      }),
    onSuccess: invalidate,
    onError,
  });

  const merge = useMutation({
    mutationFn: async ({
      sourceUid,
      targetUid,
    }: {
      sourceUid: string;
      targetUid: string;
    }) =>
      api(`${BASE}/merge?${bq(businessId)}`, {
        method: "POST",
        body: JSON.stringify({
          source_uid: sourceUid,
          target_uid: targetUid,
        }),
      }),
    onSuccess: invalidate,
    onError,
  });

  const moveModule = useMutation({
    mutationFn: async ({
      moduleUid,
      targetDomain,
    }: {
      moduleUid: string;
      targetDomain: string;
    }) =>
      api(`${BASE}/move-module?${bq(businessId)}`, {
        method: "POST",
        body: JSON.stringify({
          module_uid: moduleUid,
          target_domain: targetDomain,
        }),
      }),
    onSuccess: invalidate,
    onError,
  });

  return { rename, remove, create, move, merge, moveModule };
}
