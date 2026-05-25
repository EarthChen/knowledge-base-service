import { useCallback, useMemo, type MouseEvent } from "react";
import { Loader2 } from "lucide-react";
import { Navigate } from "react-router-dom";
import ErrorBoundary from "../ErrorBoundary";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import WikiReferencesPanel from "./WikiReferencesPanel";
import { wikiSearchHref } from "./wikiRouteHelpers";
import { useAuth } from "../../contexts/AuthContext";
import { useI18n } from "../../i18n/context";
import { api } from "../../api/client";
import { useWikiEvents } from "../../hooks/useWikiEvents";
import { useWikiPageByPath } from "../../hooks/useWikiPageByPath";
import { invalidateWikiQueriesForBusiness } from "../../hooks/invalidateWikiQueries";
import { getErrorMessage } from "../../utils/errorUtils";
import { useWikiRegenerate } from "../../hooks/useWikiRegenerate";
import WikiToolPanel, { WikiToolSuspenseFallback } from "./WikiToolPanel";
import WikiActiveTasks from "./WikiActiveTasks";
import WikiGenerationProgress from "./WikiGenerationProgress";
import WikiUpdateNotification from "./WikiUpdateNotification";
import WikiTreeNav from "./WikiTreeNav";
import WikiTopicTreeNav from "./WikiTopicTreeNav";
import type { DomainContextMenuPayload } from "./WikiTopicTreeNav";
import DomainContextMenu from "./DomainContextMenu";
import { useWikiTopicTree, type TopicTreeNode } from "../../hooks/useWikiDomainTree";
import { useDomainHierarchy } from "../../hooks/useDomainHierarchy";
import { useToast } from "../Toast";
import { useWikiShellState } from "./hooks/useWikiShellState";
import WikiDomainDialogs from "./WikiDomainDialogs";
import WikiToolbar from "./WikiToolbar";

export { WikiToolSuspenseFallback };

interface DomainHierarchyPickerNode {
  uid: string;
  title: string;
  children?: DomainHierarchyPickerNode[];
}

function mapTopicTreeNodesForHierarchyUi(nodes: TopicTreeNode[]): DomainHierarchyPickerNode[] {
  const out: DomainHierarchyPickerNode[] = [];
  for (const n of nodes) {
    const children = mapTopicTreeNodesForHierarchyUi(n.children);
    const uid = n.uid?.trim();
    if (uid) {
      out.push({
        uid,
        title: n.name,
        ...(children.length ? { children } : {}),
      });
    } else {
      out.push(...children);
    }
  }
  return out;
}

export default function WikiShell() {
  const state = useWikiShellState();
  const {
    businessId,
    pagePath,
    viewType,
    toolTab,
    wikiTier,
    searchRepo,
    wikiLinkParams,
    pendingQuery,
    wikiRegenIncremental,
    setWikiRegenIncremental,
    updateNotification,
    setUpdateNotification,
    generationStatus,
    refsPanelOpen,
    toggleRefsPanel,
    sidebarCollapsed,
    toggleSidebar,
    showCodeStructureTab,
    setTreeViewMode,
    effectiveTreeMode,
    domainContextMenu,
    setDomainContextMenu,
    wikiDomainDialog,
    setWikiDomainDialog,
    clearWikiConfirmOpen,
    setClearWikiConfirmOpen,
    clearWikiConfirmInput,
    setClearWikiConfirmInput,
    askPrefill,
    setAskPrefill,
    setViewType,
    setToolTab,
    setWikiTier,
    onTopicTreeSelect,
    handleWikiEvent,
  } = state;

  const pageQuery = useWikiPageByPath(businessId, pagePath || undefined, { repository: searchRepo });
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { t } = useI18n();
  const {
    regenerate: handleRegenerateWiki,
    isPending: regeneratePending,
    progress: regenerateProgress,
  } = useWikiRegenerate(businessId);

  const topicTreeQuery = useWikiTopicTree(businessId);
  const { rename: renameMutation, remove: removeMutation, create: createMutation, move: moveMutation, merge: mergeMutation } =
    useDomainHierarchy(businessId);

  const { isAdmin, isEditor } = useAuth();
  const clearWikiMutation = useMutation({
    mutationFn: () =>
      api<{ business_id: string; deleted_nodes: number }>(
        `/wiki/${encodeURIComponent(businessId)}`,
        { method: "DELETE" },
      ),
    onSuccess: (data) => {
      setClearWikiConfirmOpen(false);
      setClearWikiConfirmInput("");
      void invalidateWikiQueriesForBusiness(queryClient, businessId);
      toast(
        "success",
        t.wiki.clearAllWikiSuccess.replace("{count}", String(data.deleted_nodes)),
      );
    },
    onError: (err) => {
      toast("error", getErrorMessage(err, t.common.unexpectedError));
    },
  });

  const domainHierarchyTreeData = useMemo(
    () => mapTopicTreeNodesForHierarchyUi(topicTreeQuery.data?.tree ?? []),
    [topicTreeQuery.data?.tree],
  );

  const handleRenameDomain = useCallback(
    (uid: string, newDisplayName: string) => {
      renameMutation.mutate({ uid, title: newDisplayName });
    },
    [renameMutation],
  );

  const handleDeleteDomain = useCallback(
    (uid: string) => {
      removeMutation.mutate({ uid, promoteChildren: true });
    },
    [removeMutation],
  );

  const handleDomainContextMenu = useCallback((e: MouseEvent, payload: DomainContextMenuPayload) => {
    setDomainContextMenu({
      x: e.clientX,
      y: e.clientY,
      uid: payload.uid,
      title: payload.title,
      description: payload.description,
      isRoot: payload.uid?.includes("__root__") || payload.uid?.includes("__unassigned__") || false,
    });
  }, [setDomainContextMenu]);

  const { connectionStatus } = useWikiEvents(businessId.trim(), handleWikiEvent);

  if (pendingQuery.trim()) {
    return <Navigate to={wikiSearchHref(pendingQuery.trim())} replace />;
  }

  const contentError =
    pagePath && pageQuery.isError
      ? pageQuery.error instanceof Error
        ? pageQuery.error
        : new Error(getErrorMessage(pageQuery.error, t.common.unexpectedError))
      : null;

  const repoForIncremental =
    pageQuery.data?.context?.repository?.trim() || businessId.trim();

  return (
    <ErrorBoundary fallbackLabel={t.wiki.error_boundary.wiki_failed}>
      <div className="flex flex-col gap-4 lg:flex-row">
        <div
          className={`transition-all duration-300 ${sidebarCollapsed ? "w-0 overflow-hidden lg:w-0" : "w-full shrink-0 lg:sticky lg:top-0 lg:w-64 xl:w-72"}`}
        >
          {!sidebarCollapsed && (
            <div className="flex w-full flex-col gap-0">
              <div className="flex gap-1 border-b border-gray-200 p-2 dark:border-gray-700">
                <button
                  type="button"
                  onClick={() => setTreeViewMode("topic")}
                  className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                    effectiveTreeMode === "topic"
                      ? "bg-sky-100 text-sky-700 dark:bg-sky-950/40 dark:text-sky-400"
                      : "text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                  }`}
                >
                  {t.wiki.sidebar.topic_tree}
                </button>
                {showCodeStructureTab ? (
                  <button
                    type="button"
                    onClick={() => setTreeViewMode("code")}
                    className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                      effectiveTreeMode === "code"
                        ? "bg-sky-100 text-sky-700 dark:bg-sky-950/40 dark:text-sky-400"
                        : "text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                    }`}
                  >
                    {t.wiki.sidebar.code_structure}
                  </button>
                ) : null}
              </div>
              {effectiveTreeMode === "topic" ? (
                <aside className="flex w-full shrink-0 flex-col rounded-xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-900">
                  <div className="overflow-y-auto p-2 lg:max-h-[calc(100vh-10rem)]">
                    {topicTreeQuery.isLoading && (
                      <p className="flex items-center gap-2 px-2 py-4 text-sm text-gray-500 dark:text-gray-400">
                        <Loader2 className="size-4 animate-spin" aria-hidden />
                        {t.wiki.loadingPages}
                      </p>
                    )}
                    {topicTreeQuery.isError && (
                      <p className="px-2 py-3 text-sm text-red-600 dark:text-red-400">
                        {getErrorMessage(topicTreeQuery.error, t.common.unexpectedError)}
                      </p>
                    )}
                    {!topicTreeQuery.isLoading && !topicTreeQuery.isError && (
                      <WikiTopicTreeNav
                        tree={topicTreeQuery.data?.tree ?? []}
                        selectedPath={pagePath || null}
                        onSelect={onTopicTreeSelect}
                        onRenameDomain={handleRenameDomain}
                        onDeleteDomain={handleDeleteDomain}
                        onDomainContextMenu={handleDomainContextMenu}
                      />
                    )}
                  </div>
                </aside>
              ) : (
                <WikiTreeNav
                  businessId={businessId}
                  viewType={viewType}
                  activePath={pagePath}
                  onViewChange={setViewType}
                  wikiTier={wikiTier}
                  onWikiTierChange={setWikiTier}
                />
              )}
            </div>
          )}
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-4">
          {connectionStatus === "reconnecting" && (
            <div
              className="flex items-center gap-2 rounded-lg border border-amber-200/80 bg-amber-50/80 px-3 py-1.5 text-xs text-amber-950 dark:border-amber-900/50 dark:bg-amber-950/25 dark:text-amber-100"
              role="status"
              aria-live="polite"
            >
              <span
                className="size-2 shrink-0 animate-pulse rounded-full bg-amber-500 dark:bg-amber-400"
                aria-hidden
              />
              <span>{t.wiki.eventsReconnecting}</span>
            </div>
          )}
          <WikiToolbar
            sidebarCollapsed={sidebarCollapsed}
            toggleSidebar={toggleSidebar}
            toolTab={toolTab}
            setToolTab={setToolTab}
            wikiLinkParams={wikiLinkParams}
            repoForIncremental={repoForIncremental}
            isEditor={isEditor}
            isAdmin={isAdmin}
            wikiRegenIncremental={wikiRegenIncremental}
            setWikiRegenIncremental={setWikiRegenIncremental}
            regeneratePending={regeneratePending}
            handleRegenerateWiki={handleRegenerateWiki}
            regenerateProgress={regenerateProgress}
            onClearWikiClick={() => {
              setClearWikiConfirmInput("");
              clearWikiMutation.reset();
              setClearWikiConfirmOpen(true);
            }}
            clearWikiPending={clearWikiMutation.isPending}
          />

          {updateNotification && (
            <WikiUpdateNotification
              pagePath={updateNotification}
              onRefresh={() => {
                void invalidateWikiQueriesForBusiness(queryClient, businessId);
                setUpdateNotification(null);
              }}
              onDismiss={() => setUpdateNotification(null)}
            />
          )}
          <WikiActiveTasks businessId={businessId} />
          <WikiGenerationProgress status={generationStatus} />

          <WikiToolPanel
            toolTab={toolTab}
            businessId={businessId}
            viewType={viewType}
            wikiTier={wikiTier}
            pagePath={pagePath}
            pageQuery={pageQuery}
            contentError={contentError}
            wikiLinkParams={wikiLinkParams}
            onAskQuestion={(q) => {
              setAskPrefill(q);
              document.getElementById("wiki-ask-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
            askPrefill={askPrefill}
            onAskPrefillConsumed={() => setAskPrefill(undefined)}
          />
        </div>

        {toolTab === "page" && pagePath && pageQuery.data && (
          <WikiReferencesPanel
            businessId={businessId}
            pageUid={pageQuery.data.context?.uid ?? ""}
            pagePath={pageQuery.data.path}
            repository={pageQuery.data.context?.repository ?? ""}
            wikiLinkParams={wikiLinkParams}
            isOpen={refsPanelOpen}
            onToggle={toggleRefsPanel}
          />
        )}

        {domainContextMenu ? (
          <DomainContextMenu
            x={domainContextMenu.x}
            y={domainContextMenu.y}
            nodeUid={domainContextMenu.uid}
            nodeTitle={domainContextMenu.title}
            isRoot={domainContextMenu.isRoot}
            onClose={() => setDomainContextMenu(null)}
            onRename={() => {
              const cm = domainContextMenu;
              renameMutation.reset();
              setWikiDomainDialog({
                kind: "rename",
                uid: cm.uid,
                title: cm.title,
                description: cm.description ?? "",
              });
            }}
            onCreateSubdomain={() => {
              const cm = domainContextMenu;
              setWikiDomainDialog({ kind: "create", parentUid: cm.uid });
            }}
            onMove={() => {
              const cm = domainContextMenu;
              setWikiDomainDialog({ kind: "move", uid: cm.uid });
            }}
            onMerge={() => {
              const cm = domainContextMenu;
              setWikiDomainDialog({ kind: "merge", uid: cm.uid, title: cm.title });
            }}
            onDelete={() => {
              const cm = domainContextMenu;
              setWikiDomainDialog({ kind: "delete", uid: cm.uid, title: cm.title });
            }}
          />
        ) : null}

        <WikiDomainDialogs
          businessId={businessId}
          wikiDomainDialog={wikiDomainDialog}
          setWikiDomainDialog={setWikiDomainDialog}
          domainHierarchyTreeData={domainHierarchyTreeData}
          renameMutation={renameMutation}
          createMutation={createMutation}
          removeMutation={removeMutation}
          moveMutation={moveMutation}
          mergeMutation={mergeMutation}
          clearWikiConfirmOpen={clearWikiConfirmOpen}
          setClearWikiConfirmOpen={setClearWikiConfirmOpen}
          clearWikiConfirmInput={clearWikiConfirmInput}
          setClearWikiConfirmInput={setClearWikiConfirmInput}
          clearWikiMutation={clearWikiMutation}
        />
      </div>
    </ErrorBoundary>
  );
}
