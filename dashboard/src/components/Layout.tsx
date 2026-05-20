import { useState, Suspense, useRef, useLayoutEffect, useEffect } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  LayoutDashboard,
  Search,
  Network,
  FolderGit2,
  FileText,
  Database,
  Settings,
  Menu,
  X,
  Activity,
  Building2,
  ChevronDown,
  Layers,
  BookOpen,
  FolderTree,
  GitPullRequest,
  Moon,
  Sun,
} from "lucide-react";
import { useHealth } from "../api/hooks";
import { useI18n } from "../i18n/context";
import { useAuth } from "../contexts/AuthContext";
import { useBusiness } from "../contexts/BusinessContext";
import CommandPalette from "./CommandPalette";
import FocusTrap from "./FocusTrap";
import { toggleStoredTheme } from "../theme";

const SIDEBAR_BUSINESS_LISTBOX_ID = "sidebar-business-listbox";

function clampIndex(len: number, i: number) {
  if (len <= 0) return 0;
  return ((i % len) + len) % len;
}

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const mobileNavOverlayRef = useRef<HTMLDivElement>(null);
  const [bizDropdownOpen, setBizDropdownOpen] = useState(false);
  const { data: health } = useHealth();
  const { t } = useI18n();
  const { currentBusiness, setCurrentBusiness, businesses, isBound } = useBusiness();
  const { authError } = useAuth();
  const isHealthy = health?.status === "ok";

  const [darkMode, setDarkMode] = useState(
    () =>
      typeof document !== "undefined" &&
      document.documentElement.classList.contains("dark"),
  );

  function handleThemeToggle() {
    const next = toggleStoredTheme();
    setDarkMode(next === "dark");
  }

  useLayoutEffect(() => {
    if (!sidebarOpen) return;
    mobileNavOverlayRef.current?.focus({ preventScroll: true });
  }, [sidebarOpen]);

  useEffect(() => {
    if (!sidebarOpen) return;
    function onDocumentKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setSidebarOpen(false);
    }
    document.addEventListener("keydown", onDocumentKeyDown);
    return () => document.removeEventListener("keydown", onDocumentKeyDown);
  }, [sidebarOpen]);

  const businessListRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!bizDropdownOpen) return;
    const id = window.requestAnimationFrame(() => {
      const root = businessListRef.current;
      if (!root) return;
      const buttons = [
        ...root.querySelectorAll<HTMLButtonElement>("[data-biz-option]"),
      ];
      const idx = Math.max(0, businesses.findIndex((b) => b.id === currentBusiness));
      buttons[idx]?.focus();
    });
    return () => window.cancelAnimationFrame(id);
  }, [bizDropdownOpen, businesses, currentBusiness]);

  function moveBizListFocus(delta: number) {
    const root = businessListRef.current;
    if (!root) return;
    const buttons = [
      ...root.querySelectorAll<HTMLButtonElement>("[data-biz-option]"),
    ];
    if (buttons.length === 0) return;
    const active = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const idx = active >= 0 ? active : 0;
    const next = clampIndex(buttons.length, idx + delta);
    buttons[next]?.focus();
  }

  function handleBusinessListboxKeyDownCapture(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      moveBizListFocus(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      moveBizListFocus(-1);
    }
  }

  const currentBizName =
    businesses.find((b) => b.id === currentBusiness)?.name || currentBusiness;

  type NavItem = { to: string; icon: typeof LayoutDashboard; label: string };
  type NavGroup = { title: string; items: NavItem[] };

  const NAV_GROUPS: NavGroup[] = [
    {
      title: t.nav.groupExplore,
      items: [
        { to: "/", icon: LayoutDashboard, label: t.nav.overview },
        { to: "/search", icon: Search, label: t.nav.search },
        { to: "/explorer", icon: Network, label: t.nav.explorer },
        { to: "/files", icon: FolderTree, label: t.nav.files },
      ],
    },
    {
      title: t.nav.groupWiki,
      items: [
        { to: "/wiki", icon: BookOpen, label: t.nav.wiki },
        { to: "/businesses", icon: Building2, label: t.nav.businesses },
        { to: "/pr-impact", icon: GitPullRequest, label: t.nav.prImpact },
      ],
    },
    {
      title: t.nav.groupManage,
      items: [
        { to: "/repositories", icon: FolderGit2, label: t.nav.repositories },
        { to: "/indexing", icon: Database, label: t.nav.indexing },
        { to: "/architecture", icon: Layers, label: t.nav.architecture },
        { to: "/documents", icon: FileText, label: t.nav.documents },
        { to: "/settings", icon: Settings, label: t.nav.settings },
      ],
    },
  ];

  return (
    <div className="flex min-h-screen">
      {sidebarOpen && (
        <div
          ref={mobileNavOverlayRef}
          role="dialog"
          aria-modal="true"
          aria-label="Navigation"
          tabIndex={-1}
          className="fixed inset-0 z-30 bg-black/30 dark:bg-black/50 lg:hidden"
          onClick={() => setSidebarOpen(false)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setSidebarOpen(false);
          }}
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-gray-200 bg-white transition-transform duration-200 dark:border-gray-700 dark:bg-gray-900 lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex h-14 items-center gap-2.5 border-b border-gray-200 px-5 dark:border-gray-700">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-100 text-sky-600 dark:bg-sky-950 dark:text-sky-400">
            <Database size={18} />
          </div>
          <span className="text-sm font-semibold tracking-tight text-gray-900 dark:text-gray-100">
            {t.app.brandName}
          </span>
        </div>

        {/* Business selector — hidden when token is bound to a specific business */}
        {isBound ? (
          <div className="border-b border-gray-200 px-3 py-2 dark:border-gray-700">
            <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm text-gray-500 dark:border-gray-600 dark:bg-gray-800/80 dark:text-gray-400">
              <Building2 size={14} />
              <span className="truncate">{currentBizName}</span>
            </div>
          </div>
        ) : (
          <div className="relative border-b border-gray-200 px-3 py-2 dark:border-gray-700">
            <button
              type="button"
              aria-haspopup="listbox"
              aria-expanded={bizDropdownOpen}
              aria-controls={SIDEBAR_BUSINESS_LISTBOX_ID}
              onClick={() => setBizDropdownOpen(!bizDropdownOpen)}
              className="flex w-full items-center justify-between rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 transition-colors hover:border-gray-400 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:border-gray-500"
            >
              <span className="truncate">{currentBizName}</span>
              <ChevronDown
                size={14}
                aria-hidden
                className={`ml-2 shrink-0 text-gray-500 transition-transform dark:text-gray-400 ${
                  bizDropdownOpen ? "rotate-180" : ""
                }`}
              />
            </button>
            {bizDropdownOpen && (
              <FocusTrap onEscape={() => setBizDropdownOpen(false)}>
                <div
                  ref={businessListRef}
                  id={SIDEBAR_BUSINESS_LISTBOX_ID}
                  role="listbox"
                  aria-label={t.nav.businesses}
                  onKeyDownCapture={handleBusinessListboxKeyDownCapture}
                  className="absolute left-3 right-3 z-50 mt-1 max-h-48 overflow-y-auto rounded-lg border border-gray-200 bg-white py-1 shadow-xl dark:border-gray-600 dark:bg-gray-800"
                >
                  {businesses.map((biz) => (
                    <button
                      type="button"
                      role="option"
                      aria-selected={currentBusiness === biz.id}
                      data-biz-option
                      key={biz.id}
                      onClick={() => {
                        setCurrentBusiness(biz.id);
                        setBizDropdownOpen(false);
                      }}
                      className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors ${
                        currentBusiness === biz.id
                          ? "bg-sky-50 text-sky-600 dark:bg-sky-950 dark:text-sky-400"
                          : "text-gray-500 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-100"
                      }`}
                    >
                      <Building2 size={14} aria-hidden />
                      <span className="truncate">{biz.name}</span>
                    </button>
                  ))}
                </div>
              </FocusTrap>
            )}
          </div>
        )}

        <nav className="flex-1 overflow-y-auto px-3 py-4">
          {NAV_GROUPS.map((group) => (
            <div key={group.title} className="mb-4">
              <p className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
                {group.title}
              </p>
              <ul className="space-y-0.5">
                {group.items.map(({ to, icon: Icon, label }) => (
                  <li key={to}>
                    <NavLink
                      to={to}
                      end={to === "/"}
                      onClick={() => setSidebarOpen(false)}
                      className={({ isActive }) =>
                        `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                          isActive
                            ? "bg-gray-100 text-gray-900 dark:bg-gray-800 dark:text-gray-100"
                            : "text-gray-500 hover:bg-gray-100 hover:text-gray-800 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
                        }`
                      }
                    >
                      <Icon size={18} />
                      {label}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        <div className="border-t border-gray-200 px-4 py-3 dark:border-gray-700">
          <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
            <Activity size={14} />
            <span>{t.sidebar.service}</span>
            <span
              className={`inline-flex h-2 w-2 rounded-full ${
                isHealthy
                  ? "bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.6)]"
                  : "bg-amber-500"
              }`}
            />
            <span className={isHealthy ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"}>
              {isHealthy ? t.sidebar.healthy : t.sidebar.unreachable}
            </span>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center gap-3 border-b border-gray-200 bg-white px-4 dark:border-gray-700 dark:bg-gray-900 lg:px-6">
          <button
            type="button"
            aria-label="Toggle menu"
            className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800 lg:hidden"
            onClick={() => setSidebarOpen(!sidebarOpen)}
          >
            {sidebarOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
          <h1 className="min-w-0 flex-1 truncate text-sm font-medium text-gray-600 dark:text-gray-300">
            {t.app.headerTitle}
          </h1>
          <button
            type="button"
            onClick={handleThemeToggle}
            className="rounded-lg p-2 text-gray-500 transition-colors hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800"
            title={darkMode ? t.app.themeToggleLight : t.app.themeToggleDark}
            aria-label={darkMode ? t.app.themeToggleLight : t.app.themeToggleDark}
          >
            {darkMode ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <CommandPalette />
        </header>

        <main className="flex-1 bg-gray-50 p-4 dark:bg-slate-950 lg:p-6">
          {authError && (
            <div
              className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-100"
              role="alert"
            >
              {t.sidebar.authServiceUnavailable}
            </div>
          )}
          <Suspense
            fallback={
              <div className="flex items-center justify-center py-20">
                <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-300 border-t-purple-600 dark:border-gray-600 dark:border-t-purple-400" />
              </div>
            }
          >
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  );
}
