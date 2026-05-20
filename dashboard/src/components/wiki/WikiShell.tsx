import { useCallback, useEffect, useMemo, useState, type MouseEvent } from "react";
import { Loader2, PanelLeftClose, PanelLeftOpen, RefreshCw, Trash2 } from "lucide-react";
import { Navigate, useSearchParams } from "react-router-dom";
import ErrorBoundary from "../ErrorBoundary";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import WikiReferencesPanel from "./WikiReferencesPanel";
import { parseWikiSearchParams, wikiSearchHref } from "./wikiRouteHelpers";
import { useBusiness } from "../../contexts/BusinessContext";
import { useAuth } from "../../contexts/AuthContext";
import { useI18n } from "../../i18n/context";
import { api } from "../../api/client";
import type { WikiEvent, WikiEventType } from "../../hooks/wikiTypes";
import { useWikiEvents } from "../../hooks/useWikiEvents";
import { useWikiPageByPath } from "../../hooks/useWikiPageByPath";
import { invalidateWikiQueriesForBusiness } from "../../hooks/invalidateWikiQueries";
import { getErrorMessage } from "../../utils/errorUtils";
import { useWikiRegenerate } from "../../hooks/useWikiRegenerate";
import WikiToolTabStrip from "./WikiToolTabStrip";
import WikiToolPanel, { type WikiToolTab, WikiToolSuspenseFallback } from "./WikiToolPanel";
import WikiSearchBar from "./WikiSearchBar";
import WikiActiveTasks from "./WikiActiveTasks";
import WikiGenerationProgress from "./WikiGenerationProgress";
import WikiUpdateNotification from "./WikiUpdateNotification";
import WikiTreeNav from "./WikiTreeNav";
import WikiTopicTreeNav from "./WikiTopicTreeNav";
import type { DomainContextMenuPayload } from "./WikiTopicTreeNav";
import DomainContextMenu from "./DomainContextMenu";
import RenameDialog from "./dialogs/RenameDialog";
import CreateSubdomainDialog from "./dialogs/CreateSubdomainDialog";
import DeleteDialog from "./dialogs/DeleteDialog";
import MoveDialog from "./dialogs/MoveDialog";
import MergeDialog from "./dialogs/MergeDialog";
import { useWikiTopicTree, type TopicTreeNode } from "../../hooks/useWikiDomainTree";
import { useDomainHierarchy } from "../../hooks/useDomainHierarchy";
import { useToast } from "../Toast";

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

type WikiDomainDialogState =
  | null
  | { kind: "rename"; uid: string; title: string; description: string }
  | { kind: "create"; parentUid: string }
  | { kind: "delete"; uid: string; title: string }
  | { kind: "move"; uid: string }
  | { kind: "merge"; uid: string; title: string };

type DomainContextMenuState =
  | {
      x: number;
      y: number;
      uid: string;
      title: string;
      description?: string;
      isRoot: boolean;
    }
  | null;

export default function WikiShell() {
  const [searchParams, setSearchParams] = useSearchParams();
  const parsed = useMemo(() => parseWikiSearchParams(searchParams), [searchParams]);
  const { currentBusiness, setCurrentBusiness } = useBusiness();
  const businessId = parsed.businessId?.trim() || currentBusiness;

  useEffect(() => {
    const urlBiz = parsed.businessId?.trim();
    if (urlBiz && urlBiz !== currentBusiness) {
      setCurrentBusiness(urlBiz);
    }
  }, [parsed.businessId, currentBusiness, setCurrentBusiness]);

  const pagePath = parsed.path?.trim() ?? "";
  const viewType = parsed.viewType;
  const toolTab = parsed.toolTab;
  const wikiTier = parsed.wikiTier;
  const searchRepo = parsed.repo ?? undefined;

  const focusAsk = searchParams.get("focus");
  useEffect(() => {
    if (focusAsk !== "ask") return;
    const id = window.setTimeout(() => {
      document.getElementById("wiki-ask-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete("focus");
          return next;
        },
        { replace: true },
      );
    }, 0);
    return () => window.clearTimeout(id);
  }, [focusAsk, setSearchParams]);

  const wikiLinkParams = useMemo(() => {
    const p: Record<string, string> = {
      business_id: businessId,
      view: viewType,
    };
    if (wikiTier) p.wiki_tier = wikiTier;
    return p;
  }, [businessId, viewType, wikiTier]);

  const pageQuery = useWikiPageByPath(businessId, pagePath || undefined, { repository: searchRepo });
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { t } = useI18n();
  const {
    regenerate: handleRegenerateWiki,
    isPending: regeneratePending,
    progress: regenerateProgress,
  } = useWikiRegenerate(businessId);
  const [wikiRegenIncremental, setWikiRegenIncremental] = useState(true);
  const [updateNotification, setUpdateNotification] = useState<string | null>(null);
  const [generationStatus, setGenerationStatus] = useState<WikiEventType | null>(null);
  const [refsPanelOpen, setRefsPanelOpen] = useState(() => {
    try {
      return localStorage.getItem("kb_wiki_refs_panel") === "open";
    } catch {
      return false;
    }
  });

  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem("kb_wiki_sidebar") === "collapsed";
    } catch {
      return false;
    }
  });

  const showCodeStructureTab = searchParams.get("view") === "code_structure";
  const [treeViewMode, setTreeViewMode] = useState<"topic" | "code">("topic");
  const effectiveTreeMode: "topic" | "code" = showCodeStructureTab ? treeViewMode : "topic";
  const topicTreeQuery = useWikiTopicTree(businessId);
  const { rename: renameMutation, remove: removeMutation, create: createMutation, move: moveMutation, merge: mergeMutation } =
    useDomainHierarchy(businessId);

  const [domainContextMenu, setDomainContextMenu] = useState<DomainContextMenuState>(null);
  const [wikiDomainDialog, setWikiDomainDialog] = useState<WikiDomainDialogState>(null);
  const { isAdmin } = useAuth();
  const [clearWikiConfirmOpen, setClearWikiConfirmOpen] = useState(false);
  const [clearWikiConfirmInput, setClearWikiConfirmInput] = useState("");
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
      isRoot: payload.uid?.includes('__root__') || payload.uid?.includes('__unassigned__') || false,
    });
  }, []);
  const onTopicTreeSelect = useCallback(
    (path: string) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("path", path);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("kb_wiki_sidebar", next ? "collapsed" : "open");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const toggleRefsPanel = useCallback(() => {
    setRefsPanelOpen((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("kb_wiki_refs_panel", next ? "open" : "closed");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const handleWikiEvent = useCallback(
    (event: WikiEvent) => {
      if (event.type === "wiki:page_updated" && event.page_path) {
        setUpdateNotification(event.page_path);
      } else if (
        event.type === "wiki:generation_started" ||
        event.type === "wiki:generation_completed" ||
        event.type === "wiki:generation_failed"
      ) {
        setGenerationStatus(event.type);
        if (event.type === "wiki:generation_completed") {
          void invalidateWikiQueriesForBusiness(queryClient, businessId);
        }
      }
    },
    [queryClient, businessId],
  );

  const { connectionStatus } = useWikiEvents(businessId.trim(), handleWikiEvent);

  const setViewType = useCallback(
    (v: typeof viewType) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (v === "business_domain") next.delete("view");
          else next.set("view", v);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const pendingQuery = searchParams.get("q") ?? "";
  if (pendingQuery.trim()) {
    return <Navigate to={wikiSearchHref(pendingQuery.trim())} replace />;
  }

  const setToolTab = useCallback(
    (tab: WikiToolTab) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (tab === "page") next.delete("tool");
          else next.set("tool", tab);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const setWikiTier = useCallback(
    (tier: string | null) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (tier) next.set("wiki_tier", tier);
          else next.delete("wiki_tier");
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

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
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 shadow-sm dark:border-gray-700 dark:bg-gray-900">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={toggleSidebar}
                className="hidden items-center justify-center rounded-md border border-gray-200 bg-white p-1.5 text-gray-500 hover:bg-gray-50 hover:text-gray-700 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200 lg:flex"
                aria-label={sidebarCollapsed ? t.wiki.sidebarExpand : t.wiki.sidebarCollapse}
                title={sidebarCollapsed ? t.wiki.sidebarExpand : t.wiki.sidebarCollapse}
              >
                {sidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
              </button>
              <WikiToolTabStrip toolTab={toolTab} onToolTabChange={setToolTab} />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <WikiSearchBar linkParams={wikiLinkParams} repository={repoForIncremental} />
              <div
                className="inline-flex shrink-0 overflow-hidden rounded-lg border border-gray-200 text-xs font-medium dark:border-gray-600"
                role="group"
                aria-label={t.wiki.regenerate}
              >
                <button
                  type="button"
                  onClick={() => setWikiRegenIncremental(true)}
                  disabled={regeneratePending}
                  className={`px-2.5 py-2 transition-colors ${
                    wikiRegenIncremental
                      ? "bg-amber-100 text-amber-950 dark:bg-amber-950/60 dark:text-amber-100"
                      : "bg-white text-gray-600 hover:bg-gray-50 dark:bg-gray-900 dark:text-gray-300 dark:hover:bg-gray-800"
                  }`}
                >
                  {t.wiki.regenerateIncremental}
                </button>
                <button
                  type="button"
                  onClick={() => setWikiRegenIncremental(false)}
                  disabled={regeneratePending}
                  className={`border-l border-gray-200 px-2.5 py-2 transition-colors dark:border-gray-600 ${
                    !wikiRegenIncremental
                      ? "bg-amber-100 text-amber-950 dark:bg-amber-950/60 dark:text-amber-100"
                      : "bg-white text-gray-600 hover:bg-gray-50 dark:bg-gray-900 dark:text-gray-300 dark:hover:bg-gray-800"
                  }`}
                >
                  {t.wiki.regenerateFull}
                </button>
              </div>
              <button
                type="button"
                onClick={() => void handleRegenerateWiki(wikiRegenIncremental)}
                disabled={regeneratePending}
                aria-busy={regeneratePending}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-900 hover:bg-amber-100 disabled:opacity-50 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-200 dark:hover:bg-amber-950"
              >
                {regeneratePending ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <RefreshCw size={14} aria-hidden />}
                {t.wiki.regenerate}
              </button>
              {isAdmin && (
                <button
                  type="button"
                  onClick={() => {
                    setClearWikiConfirmInput("");
                    clearWikiMutation.reset();
                    setClearWikiConfirmOpen(true);
                  }}
                  disabled={clearWikiMutation.isPending}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-100 disabled:opacity-50 dark:border-red-900 dark:bg-red-950/50 dark:text-red-300 dark:hover:bg-red-950"
                >
                  <Trash2 size={14} aria-hidden />
                  {t.wiki.clearAllWiki}
                </button>
              )}
            </div>
          </div>

          {regenerateProgress && (
            <div className="space-y-1.5 rounded-lg border border-amber-200/80 bg-amber-50/50 px-3 py-2 dark:border-amber-900/50 dark:bg-amber-950/20">
              <p className="text-xs text-amber-950 dark:text-amber-100">
                {t.wiki.regenerateProgress
                  .replace("{current}", regenerateProgress.currentRepo || "—")
                  .replace("{pct}", String(Math.round(regenerateProgress.progressPct)))}
              </p>
              {regenerateProgress.skippedRepos > 0 && (
                <p className="text-xs text-gray-600 dark:text-gray-400">
                  {t.wiki.regenerateSkipped.replace("{count}", String(regenerateProgress.skippedRepos))}
                </p>
              )}
              <div
                className="h-2 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700"
                role="progressbar"
                aria-valuenow={Math.round(regenerateProgress.progressPct)}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={t.wiki.regenerateProgress
                  .replace("{current}", regenerateProgress.currentRepo || "—")
                  .replace("{pct}", String(Math.round(regenerateProgress.progressPct)))}
              >
                <div
                  className="h-full rounded-full bg-amber-500 transition-[width] dark:bg-amber-600"
                  style={{ width: `${Math.min(100, Math.max(0, regenerateProgress.progressPct))}%` }}
                />
              </div>
            </div>
          )}

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
              const el = document.getElementById("wiki-ask-panel");
              if (el) {
                el.scrollIntoView({ behavior: "smooth", block: "start" });
                const input = el.querySelector<HTMLTextAreaElement>("textarea");
                if (input) {
                  input.value = q;
                  input.dispatchEvent(new Event("input", { bubbles: true }));
                  input.focus();
                }
              }
            }}
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
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setClearWikiConfirmOpen(false)}>
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
                    clearWikiMutation.error instanceof Error ? clearWikiMutation.error.message : String(clearWikiMutation.error),
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
      </div>
    </ErrorBoundary>
  );
}
