import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import { ToastProvider } from "./components/Toast";
import Overview from "./pages/Overview";
import SearchPage from "./pages/SearchPage";
import GraphQuery from "./pages/GraphQuery";
import GraphExplorer from "./pages/GraphExplorer";
import Repositories from "./pages/Repositories";
import Indexing from "./pages/Indexing";
import SettingsPage from "./pages/SettingsPage";

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Overview />} />
          <Route path="search" element={<SearchPage />} />
          <Route path="graph" element={<GraphQuery />} />
          <Route path="explorer" element={<GraphExplorer />} />
          <Route path="repositories" element={<Repositories />} />
          <Route path="indexing" element={<Indexing />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </ToastProvider>
  );
}
