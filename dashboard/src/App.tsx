import { lazy } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
import ErrorBoundary from "./components/ErrorBoundary";
import { ToastProvider } from "./components/Toast";

const Overview = lazy(() => import("./pages/Overview"));
const SearchPage = lazy(() => import("./pages/SearchPage"));
const GraphExplorer = lazy(() => import("./pages/GraphExplorer"));
const ArchitecturePage = lazy(() => import("./pages/ArchitecturePage"));
const Repositories = lazy(() => import("./pages/Repositories"));
const Indexing = lazy(() => import("./pages/Indexing"));
const Documents = lazy(() => import("./pages/Documents"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const WikiPage = lazy(() => import("./pages/WikiPage"));
const PrImpactPage = lazy(() => import("./pages/PrImpactPage"));
const Businesses = lazy(() => import("./pages/Businesses"));
const FileExplorer = lazy(() => import("./pages/FileExplorer"));
const NotFound = lazy(() => import("./pages/NotFound"));

export default function App() {
  return (
    <ToastProvider>
      <ErrorBoundary>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Overview />} />
            <Route path="search" element={<SearchPage />} />
            <Route path="explorer" element={<GraphExplorer />} />
            <Route path="files" element={<FileExplorer />} />
            <Route path="architecture" element={<ArchitecturePage />} />
            <Route path="repositories" element={<Repositories />} />
            <Route path="documents" element={<Documents />} />
            <Route path="indexing" element={<Indexing />} />
            <Route path="wiki" element={<WikiPage />} />
            <Route path="pr-impact" element={<PrImpactPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="deep-search" element={<Navigate to="/search" replace />} />
            <Route path="graph" element={<Navigate to="/explorer" replace />} />
            <Route path="businesses" element={<Businesses />} />
          </Route>
          <Route path="*" element={<NotFound />} />
        </Routes>
      </ErrorBoundary>
    </ToastProvider>
  );
}
