import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  LayoutDashboard,
  Search,
  GitFork,
  Network,
  FolderGit2,
  Database,
  Settings,
  Menu,
  X,
  Activity,
} from "lucide-react";
import { useHealth } from "../api/hooks";
import { useI18n } from "../i18n/context";

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { data: health } = useHealth();
  const { t } = useI18n();
  const isHealthy = health?.status === "ok";

  const NAV = [
    { to: "/", icon: LayoutDashboard, label: t.nav.overview },
    { to: "/search", icon: Search, label: t.nav.search },
    { to: "/graph", icon: GitFork, label: t.nav.graphQuery },
    { to: "/explorer", icon: Network, label: t.nav.explorer },
    { to: "/repositories", icon: FolderGit2, label: t.nav.repositories },
    { to: "/indexing", icon: Database, label: t.nav.indexing },
    { to: "/settings", icon: Settings, label: t.nav.settings },
  ] as const;

  return (
    <div className="flex h-screen overflow-hidden">
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-slate-800 bg-slate-925 transition-transform duration-200 lg:static lg:translate-x-0 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex h-14 items-center gap-2.5 border-b border-slate-800 px-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-500/15 text-sky-400">
            <Database size={18} />
          </div>
          <span className="text-sm font-semibold tracking-tight text-white">
            Knowledge Base
          </span>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4">
          <ul className="space-y-1">
            {NAV.map(({ to, icon: Icon, label }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={to === "/"}
                  onClick={() => setSidebarOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                      isActive
                        ? "bg-slate-800 text-white"
                        : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200"
                    }`
                  }
                >
                  <Icon size={18} />
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <div className="border-t border-slate-800 px-4 py-3">
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Activity size={14} />
            <span>{t.sidebar.service}</span>
            <span
              className={`inline-flex h-2 w-2 rounded-full ${
                isHealthy
                  ? "bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.6)]"
                  : "bg-amber-500"
              }`}
            />
            <span className={isHealthy ? "text-emerald-400" : "text-amber-400"}>
              {isHealthy ? t.sidebar.healthy : t.sidebar.unreachable}
            </span>
          </div>
        </div>
      </aside>

      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-14 items-center gap-3 border-b border-slate-800 px-4 lg:px-6">
          <button
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 lg:hidden"
            onClick={() => setSidebarOpen(!sidebarOpen)}
          >
            {sidebarOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
          <h1 className="text-sm font-medium text-slate-300">
            {t.app.headerTitle}
          </h1>
        </header>

        <main className="flex-1 overflow-y-auto p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
