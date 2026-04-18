import { lazy, Suspense } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import { ToastProvider } from "./components/Toast";
import Overview from "./pages/Overview";
import SearchPage from "./pages/SearchPage";
import GraphExplorer from "./pages/GraphExplorer";
import ArchitecturePage from "./pages/ArchitecturePage";
import Repositories from "./pages/Repositories";
import Indexing from "./pages/Indexing";
import Documents from "./pages/Documents";
import SettingsPage from "./pages/SettingsPage";
import WikiPage from "./pages/WikiPage";
import PrImpactPage from "./pages/PrImpactPage";

const Businesses = lazy(() => import("./pages/Businesses"));

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Overview />} />
          <Route path="search" element={<SearchPage />} />
          <Route path="explorer" element={<GraphExplorer />} />
          <Route path="architecture" element={<ArchitecturePage />} />
          <Route path="repositories" element={<Repositories />} />
          <Route path="documents" element={<Documents />} />
          <Route path="indexing" element={<Indexing />} />
          <Route path="wiki/*" element={<WikiPage />} />
          <Route path="pr-impact" element={<PrImpactPage />} />
          <Route path="settings" element={<SettingsPage />} />
          {/* Legacy routes — redirect or lazy-load for backward compat */}
          <Route path="deep-search" element={<Navigate to="/search" replace />} />
          <Route path="graph" element={<Navigate to="/explorer" replace />} />
          <Route path="businesses" element={<Suspense fallback={null}><Businesses /></Suspense>} />
        </Route>
      </Routes>
    </ToastProvider>
  );
}
