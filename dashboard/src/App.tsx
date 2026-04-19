import { lazy } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "./components/Layout";
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
          <Route path="wiki">
            <Route index element={<WikiPage />} />
            <Route path=":repository/*" element={<WikiPage />} />
          </Route>
          <Route path="pr-impact" element={<PrImpactPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="deep-search" element={<Navigate to="/search" replace />} />
          <Route path="graph" element={<Navigate to="/explorer" replace />} />
          <Route path="businesses" element={<Businesses />} />
        </Route>
      </Routes>
    </ToastProvider>
  );
}
