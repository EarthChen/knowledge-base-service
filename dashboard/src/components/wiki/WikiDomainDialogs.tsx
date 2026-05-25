import type { UseMutationResult } from "@tanstack/react-query";
import { useI18n } from "../../i18n/context";
import RenameDialog from "./dialogs/RenameDialog";
import CreateSubdomainDialog from "./dialogs/CreateSubdomainDialog";
import DeleteDialog from "./dialogs/DeleteDialog";
import MoveDialog from "./dialogs/MoveDialog";
import MergeDialog from "./dialogs/MergeDialog";
import type { WikiDomainDialogState } from "./hooks/useWikiShellState";

interface DomainHierarchyPickerNode {
  uid: string;
  title: string;
  children?: DomainHierarchyPickerNode[];
}

interface DomainRenameMutation {
  mutate: (
    vars: { uid: string; title?: string; description?: string },
    opts?: { onSuccess?: () => void },
  ) => void;
  reset: () => void;
  isError: boolean;
  isPending: boolean;
}

interface DomainCreateMutation {
  mutate: (vars: { parentUid: string; title: string; description: string }) => void;
}

interface DomainRemoveMutation {
  mutate: (vars: { uid: string; promoteChildren: boolean }) => void;
}

interface DomainMoveMutation {
  mutate: (vars: { uid: string; targetParentUid: string }) => void;
}

interface DomainMergeMutation {
  mutate: (vars: { sourceUid: string; targetUid: string }) => void;
}

interface ClearWikiMutation extends Pick<
  UseMutationResult<{ business_id: string; deleted_nodes: number }, Error, void, unknown>,
  "mutate" | "reset" | "isError" | "isPending" | "error"
> {}

export interface WikiDomainDialogsProps {
  businessId: string;
  wikiDomainDialog: WikiDomainDialogState;
  setWikiDomainDialog: (state: WikiDomainDialogState) => void;
  domainHierarchyTreeData: DomainHierarchyPickerNode[];
  renameMutation: DomainRenameMutation;
  createMutation: DomainCreateMutation;
  removeMutation: DomainRemoveMutation;
  moveMutation: DomainMoveMutation;
  mergeMutation: DomainMergeMutation;
  clearWikiConfirmOpen: boolean;
  setClearWikiConfirmOpen: (open: boolean) => void;
  clearWikiConfirmInput: string;
  setClearWikiConfirmInput: (value: string) => void;
  clearWikiMutation: ClearWikiMutation;
}

export default function WikiDomainDialogs({
  businessId,
  wikiDomainDialog,
  setWikiDomainDialog,
  domainHierarchyTreeData,
  renameMutation,
  createMutation,
  removeMutation,
  moveMutation,
  mergeMutation,
  clearWikiConfirmOpen,
  setClearWikiConfirmOpen,
  clearWikiConfirmInput,
  setClearWikiConfirmInput,
  clearWikiMutation,
}: WikiDomainDialogsProps) {
  const { t } = useI18n();

  return (
    <>
      {wikiDomainDialog?.kind === "rename" ? (
        <RenameDialog
          currentTitle={wikiDomainDialog.title}
          currentDescription={wikiDomainDialog.description}
          isError={renameMutation.isError}
          isPending={renameMutation.isPending}
          onConfirm={(title, description) => {
            renameMutation.mutate(
              {
                uid: wikiDomainDialog.uid,
                title: title.trim() || wikiDomainDialog.title,
                description: description.trim(),
              },
              { onSuccess: () => setWikiDomainDialog(null) },
            );
          }}
          onCancel={() => {
            renameMutation.reset();
            setWikiDomainDialog(null);
          }}
        />
      ) : null}
      {wikiDomainDialog?.kind === "create" ? (
        <CreateSubdomainDialog
          onConfirm={(title, description) => {
            createMutation.mutate({
              parentUid: wikiDomainDialog.parentUid,
              title,
              description: description.trim(),
            });
            setWikiDomainDialog(null);
          }}
          onCancel={() => setWikiDomainDialog(null)}
        />
      ) : null}
      {wikiDomainDialog?.kind === "delete" ? (
        <DeleteDialog
          domainTitle={wikiDomainDialog.title}
          onConfirm={(promoteChildren) => {
            removeMutation.mutate({ uid: wikiDomainDialog.uid, promoteChildren });
            setWikiDomainDialog(null);
          }}
          onCancel={() => setWikiDomainDialog(null)}
        />
      ) : null}
      {wikiDomainDialog?.kind === "move" ? (
        <MoveDialog
          currentUid={wikiDomainDialog.uid}
          treeData={domainHierarchyTreeData}
          onConfirm={(targetParentUid) => {
            moveMutation.mutate({ uid: wikiDomainDialog.uid, targetParentUid });
            setWikiDomainDialog(null);
          }}
          onCancel={() => setWikiDomainDialog(null)}
        />
      ) : null}
      {wikiDomainDialog?.kind === "merge" ? (
        <MergeDialog
          sourceUid={wikiDomainDialog.uid}
          sourceTitle={wikiDomainDialog.title}
          treeData={domainHierarchyTreeData}
          onConfirm={(targetUid) => {
            mergeMutation.mutate({ sourceUid: wikiDomainDialog.uid, targetUid });
            setWikiDomainDialog(null);
          }}
          onCancel={() => setWikiDomainDialog(null)}
        />
      ) : null}

      {clearWikiConfirmOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          onClick={() => setClearWikiConfirmOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-6 shadow-xl dark:border-gray-700 dark:bg-gray-900"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="mb-2 text-lg font-semibold text-red-700 dark:text-red-400">
              {t.wiki.clearAllWikiConfirmTitle}
            </h3>
            <p className="mb-4 text-sm text-gray-600 dark:text-gray-400">
              {t.wiki.clearAllWikiConfirmBody.replace("{businessId}", businessId)}
            </p>
            <input
              type="text"
              value={clearWikiConfirmInput}
              onChange={(e) => setClearWikiConfirmInput(e.target.value)}
              placeholder={t.wiki.clearAllWikiConfirmPlaceholder}
              className="mb-4 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-red-500 focus:outline-none focus:ring-1 focus:ring-red-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200"
              autoFocus
            />
            {clearWikiMutation.isError && (
              <p className="mb-3 text-sm text-red-600 dark:text-red-400">
                {t.wiki.clearAllWikiFailed.replace(
                  "{detail}",
                  clearWikiMutation.error instanceof Error
                    ? clearWikiMutation.error.message
                    : String(clearWikiMutation.error),
                )}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setClearWikiConfirmOpen(false)}
                className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800"
              >
                {t.wiki.domain_management.cancel}
              </button>
              <button
                type="button"
                disabled={clearWikiConfirmInput !== businessId || clearWikiMutation.isPending}
                onClick={() => clearWikiMutation.mutate()}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700 disabled:opacity-50"
              >
                {clearWikiMutation.isPending ? t.wiki.clearAllWikiPending : t.wiki.clearAllWiki}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
