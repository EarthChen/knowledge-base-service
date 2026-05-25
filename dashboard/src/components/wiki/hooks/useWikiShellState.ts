import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useBusiness } from "../../../contexts/BusinessContext";
import { parseWikiSearchParams } from "../wikiRouteHelpers";
import type { WikiEvent, WikiEventType } from "../../../hooks/wikiTypes";
import { invalidateWikiQueriesForBusiness } from "../../../hooks/invalidateWikiQueries";
import type { WikiToolTab } from "../WikiToolPanel";

export type WikiDomainDialogState =
  | null
  | { kind: "rename"; uid: string; title: string; description: string }
  | { kind: "create"; parentUid: string }
  | { kind: "delete"; uid: string; title: string }
  | { kind: "move"; uid: string }
  | { kind: "merge"; uid: string; title: string };

export type DomainContextMenuState =
  | {
      x: number;
      y: number;
      uid: string;
      title: string;
      description?: string;
      isRoot: boolean;
    }
  | null;

export interface UseWikiShellStateResult {
  businessId: string;
  pagePath: string;
  viewType: "business_domain" | "code_structure";
  toolTab: WikiToolTab;
  wikiTier: "standard" | "essential" | "comprehensive" | null;
  searchRepo: string | undefined;
  wikiLinkParams: Record<string, string>;
  pendingQuery: string;
  wikiRegenIncremental: boolean;
  setWikiRegenIncremental: (value: boolean) => void;
  updateNotification: string | null;
  setUpdateNotification: (value: string | null) => void;
  generationStatus: WikiEventType | null;
  refsPanelOpen: boolean;
  toggleRefsPanel: () => void;
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  showCodeStructureTab: boolean;
  treeViewMode: "topic" | "code";
  setTreeViewMode: (mode: "topic" | "code") => void;
  effectiveTreeMode: "topic" | "code";
  domainContextMenu: DomainContextMenuState;
  setDomainContextMenu: (state: DomainContextMenuState) => void;
  wikiDomainDialog: WikiDomainDialogState;
  setWikiDomainDialog: (state: WikiDomainDialogState) => void;
  clearWikiConfirmOpen: boolean;
  setClearWikiConfirmOpen: (open: boolean) => void;
  clearWikiConfirmInput: string;
  setClearWikiConfirmInput: (value: string) => void;
  askPrefill: string | undefined;
  setAskPrefill: (value: string | undefined) => void;
  setViewType: (v: "business_domain" | "code_structure") => void;
  setToolTab: (tab: WikiToolTab) => void;
  setWikiTier: (tier: string | null) => void;
  onTopicTreeSelect: (path: string) => void;
  handleWikiEvent: (event: WikiEvent) => void;
}

export function useWikiShellState(): UseWikiShellStateResult {
  const [searchParams, setSearchParams] = useSearchParams();
  const parsed = useMemo(() => parseWikiSearchParams(searchParams), [searchParams]);
  const { currentBusiness, setCurrentBusiness } = useBusiness();
  const businessId = parsed.businessId?.trim() || currentBusiness;
  const queryClient = useQueryClient();

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

  const [domainContextMenu, setDomainContextMenu] = useState<DomainContextMenuState>(null);
  const [wikiDomainDialog, setWikiDomainDialog] = useState<WikiDomainDialogState>(null);
  const [clearWikiConfirmOpen, setClearWikiConfirmOpen] = useState(false);
  const [clearWikiConfirmInput, setClearWikiConfirmInput] = useState("");
  const [askPrefill, setAskPrefill] = useState<string | undefined>(undefined);

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

  const pendingQuery = searchParams.get("q") ?? "";

  return {
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
    treeViewMode,
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
  };
}
