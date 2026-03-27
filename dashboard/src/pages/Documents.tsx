import { useMemo, useState } from "react";
import { FileText, Folder, Loader2 } from "lucide-react";
import { useDocuments, useDocument, useRepositories } from "../api/hooks";
import type { DocumentItem } from "../api/types";
import { useI18n } from "../i18n/context";
import { SkeletonLine } from "../components/Skeleton";
import MarkdownRenderer from "../components/MarkdownRenderer";

interface TreeNode {
  dirs: Record<string, TreeNode>;
  files: DocumentItem[];
}

function emptyTree(): TreeNode {
  return { dirs: {}, files: [] };
}

function addDocument(root: TreeNode, doc: DocumentItem) {
  const normalized = doc.file.replace(/\\/g, "/");
  const parts = normalized.split("/").filter(Boolean);
  if (parts.length === 0) {
    root.files.push(doc);
    return;
  }
  parts.pop();
  let node = root;
  for (const part of parts) {
    if (!node.dirs[part]) node.dirs[part] = emptyTree();
    node = node.dirs[part];
  }
  node.files.push(doc);
}

function buildTree(docs: DocumentItem[]): TreeNode {
  const root = emptyTree();
  for (const doc of docs) {
    addDocument(root, doc);
  }
  return root;
}

function TreeView({
  node,
  depth,
  selectedUid,
  onSelect,
}: {
  node: TreeNode;
  depth: number;
  selectedUid: string | null;
  onSelect: (uid: string) => void;
}) {
  const dirNames = Object.keys(node.dirs).sort();
  const sortedFiles = [...node.files].sort((a, b) => a.title.localeCompare(b.title));
  const pad = 8 + depth * 12;

  return (
    <>
      {dirNames.map((dn) => (
        <div key={`${depth}-${dn}`} className="select-none">
          <div
            className="flex items-center gap-2 py-1.5 text-sm text-slate-500"
            style={{ paddingLeft: pad }}
          >
            <Folder size={16} className="shrink-0 text-amber-500/90" />
            <span className="truncate font-medium">{dn}</span>
          </div>
          <TreeView
            node={node.dirs[dn]}
            depth={depth + 1}
            selectedUid={selectedUid}
            onSelect={onSelect}
          />
        </div>
      ))}
      {sortedFiles.map((doc) => (
        <button
          key={doc.uid}
          type="button"
          onClick={() => onSelect(doc.uid)}
          className={`flex w-full items-center gap-2 rounded-lg py-1.5 pr-2 text-left text-sm transition-colors ${
            selectedUid === doc.uid
              ? "bg-sky-500/15 text-sky-400"
              : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200"
          }`}
          style={{ paddingLeft: pad }}
        >
          <FileText size={16} className="shrink-0 text-slate-500" />
          <span className="truncate">{doc.title}</span>
        </button>
      ))}
    </>
  );
}

export default function Documents() {
  const { t } = useI18n();
  const [repository, setRepository] = useState<string>("");
  const [selectedUid, setSelectedUid] = useState<string | null>(null);

  const { data: reposData } = useRepositories();
  const {
    data: listData,
    isLoading: listLoading,
    error: listError,
  } = useDocuments(repository || undefined);
  const {
    data: detail,
    isLoading: detailLoading,
    error: detailError,
  } = useDocument(selectedUid);

  const tree = useMemo(
    () => buildTree(listData?.documents ?? []),
    [listData?.documents],
  );

  const repos = reposData?.repositories ?? [];

  function scrollToSection(uid: string) {
    const el = document.getElementById(`doc-section-${uid}`);
    el?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
          <FileText size={20} /> {t.documents.title}
        </h2>
      </div>

      <div className="flex min-h-[calc(100vh-10rem)] flex-col gap-4 lg:flex-row">
        <aside className="flex min-h-0 w-full shrink-0 flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-800/50 lg:w-72">
        <div className="border-b border-slate-800 p-3">
          <label className="mb-1 block text-xs font-medium text-slate-500">
            {t.repos.repository}
          </label>
          <select
            value={repository}
            onChange={(e) => {
              setRepository(e.target.value);
              setSelectedUid(null);
            }}
            className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-300 outline-none ring-sky-500/30 focus:ring-2"
          >
            <option value="">{t.documents.allRepos}</option>
            {repos.map((r) => (
              <option key={r.repository} value={r.repository}>
                {r.repository}
              </option>
            ))}
          </select>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {listLoading ? (
            <div className="space-y-2 p-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <SkeletonLine key={i} className="h-4 w-full" />
              ))}
            </div>
          ) : listError ? (
            <div className="p-3 text-sm text-red-400">
              {(listError as Error).message}
            </div>
          ) : (listData?.documents.length ?? 0) === 0 ? (
            <div className="p-3 text-sm text-slate-500">{t.search.noResults}</div>
          ) : (
            <TreeView
              node={tree}
              depth={0}
              selectedUid={selectedUid}
              onSelect={setSelectedUid}
            />
          )}
        </div>
        </aside>

        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-800/50">
        {!selectedUid ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center text-slate-500">
            <FileText size={40} className="text-slate-600" />
            <p className="text-sm">{t.documents.selectDoc}</p>
          </div>
        ) : detailLoading ? (
          <div className="flex flex-1 items-center justify-center gap-2 text-slate-500">
            <Loader2 size={20} className="animate-spin" />
            <span className="text-sm">{t.search.searching}</span>
          </div>
        ) : detailError ? (
          <div className="p-6 text-sm text-red-400">
            {(detailError as Error).message}
          </div>
        ) : detail ? (
          <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
            <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden border-b border-slate-800 lg:border-b-0 lg:border-r">
              <div className="shrink-0 border-b border-slate-800 p-4">
                <h2 className="text-lg font-semibold text-white">{detail.title}</h2>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span className="font-mono text-slate-400">{detail.file}</span>
                  <span className="rounded-md border border-slate-700 bg-slate-900/80 px-2 py-0.5 text-sky-400">
                    {detail.repository}
                  </span>
                </div>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-4">
                {detail.sections.map((section) => (
                  <div
                    key={section.uid}
                    id={`doc-section-${section.uid}`}
                    className="scroll-mt-4 border-b border-slate-800/80 pb-6 last:border-0 last:pb-0"
                  >
                    <h3 className="mb-3 text-sm font-semibold text-slate-200">
                      {section.title}
                    </h3>
                    <MarkdownRenderer content={section.content} />
                  </div>
                ))}
              </div>
            </div>
            {detail.sections.length > 0 && (
              <nav className="w-full shrink-0 border-t border-slate-800 p-3 lg:w-52 lg:border-l lg:border-t-0">
                <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
                  {t.documents.sections}
                </p>
                <ul className="max-h-48 space-y-1 overflow-y-auto lg:max-h-none">
                  {detail.sections.map((s) => (
                    <li key={s.uid}>
                      <button
                        type="button"
                        onClick={() => scrollToSection(s.uid)}
                        className="w-full rounded-lg px-2 py-1.5 text-left text-xs text-slate-400 transition-colors hover:bg-slate-800/80 hover:text-sky-400"
                      >
                        {s.title}
                      </button>
                    </li>
                  ))}
                </ul>
              </nav>
            )}
          </div>
        ) : null}
        </div>
      </div>
    </div>
  );
}
