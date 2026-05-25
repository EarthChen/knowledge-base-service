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
            <Route index element={<ErrorBoundary><Overview /></ErrorBoundary>} />
            <Route path="search" element={<ErrorBoundary><SearchPage /></ErrorBoundary>} />
            <Route path="explorer" element={<ErrorBoundary><GraphExplorer /></ErrorBoundary>} />
            <Route path="files" element={<ErrorBoundary><FileExplorer /></ErrorBoundary>} />
            <Route path="architecture" element={<ErrorBoundary><ArchitecturePage /></ErrorBoundary>} />
            <Route path="repositories" element={<ErrorBoundary><Repositories /></ErrorBoundary>} />
            <Route path="documents" element={<ErrorBoundary><Documents /></ErrorBoundary>} />
            <Route path="indexing" element={<ErrorBoundary><Indexing /></ErrorBoundary>} />
            <Route path="wiki" element={<ErrorBoundary><WikiPage /></ErrorBoundary>} />
            <Route path="pr-impact" element={<ErrorBoundary><PrImpactPage /></ErrorBoundary>} />
            <Route path="settings" element={<ErrorBoundary><SettingsPage /></ErrorBoundary>} />
            <Route path="deep-search" element={<Navigate to="/search" replace />} />
            <Route path="graph" element={<Navigate to="/explorer" replace />} />
            <Route path="businesses" element={<ErrorBoundary><Businesses /></ErrorBoundary>} />
          </Route>
          <Route path="*" element={<ErrorBoundary><NotFound /></ErrorBoundary>} />
        </Routes>
      </ErrorBoundary>
    </ToastProvider>
  );
}
