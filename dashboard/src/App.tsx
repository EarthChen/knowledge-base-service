import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import { ToastProvider } from "./components/Toast";
import Overview from "./pages/Overview";
import SearchPage from "./pages/SearchPage";
import DeepSearchPage from "./pages/DeepSearchPage";
import GraphQuery from "./pages/GraphQuery";
import GraphExplorer from "./pages/GraphExplorer";
import ArchitecturePage from "./pages/ArchitecturePage";
import Repositories from "./pages/Repositories";
import Indexing from "./pages/Indexing";
import Businesses from "./pages/Businesses";
import Documents from "./pages/Documents";
import SettingsPage from "./pages/SettingsPage";
import WikiPage from "./pages/WikiPage";

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Overview />} />
          <Route path="search" element={<SearchPage />} />
          <Route path="deep-search" element={<DeepSearchPage />} />
          <Route path="graph" element={<GraphQuery />} />
          <Route path="explorer" element={<GraphExplorer />} />
          <Route path="architecture" element={<ArchitecturePage />} />
          <Route path="repositories" element={<Repositories />} />
          <Route path="documents" element={<Documents />} />
          <Route path="indexing" element={<Indexing />} />
          <Route path="businesses" element={<Businesses />} />
          <Route path="wiki/*" element={<WikiPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </ToastProvider>
  );
}
