import { useState } from "react";
import { Database, Loader2 } from "lucide-react";
import { useIndex } from "../api/hooks";
import { useI18n } from "../i18n/context";
import { useToast } from "../components/Toast";
import JsonView from "../components/JsonView";

export default function Indexing() {
  const [mode, setMode] = useState<"full" | "incremental">("full");
  const [directory, setDirectory] = useState("");
  const [repository, setRepository] = useState("");
  const [baseRef, setBaseRef] = useState("HEAD~1");
  const [headRef, setHeadRef] = useState("HEAD");

  const { t } = useI18n();
  const mutation = useIndex();
  const { toast } = useToast();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!directory.trim()) {
      toast("error", t.indexing.directoryRequired);
      return;
    }

    const body: Record<string, unknown> = {
      directory: directory.trim(),
      mode,
    };
    if (mode === "incremental") {
      body.base_ref = baseRef;
      body.head_ref = headRef;
    }
    if (repository.trim()) body.repository = repository.trim();

    try {
      await mutation.mutateAsync(body);
      toast("success", t.indexing.indexingComplete);
    } catch (err) {
      toast("error", (err as Error).message || t.indexing.indexingFailed);
    }
  }

  const inputClass =
    "w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white placeholder-slate-500 outline-none focus:border-sky-500/50 focus:ring-1 focus:ring-sky-500/30";

  return (
    <div className="space-y-6">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
        <Database size={20} /> {t.indexing.title}
      </h2>

      <form
        onSubmit={handleSubmit}
        className="space-y-4 rounded-xl border border-slate-800 bg-slate-850 p-5"
      >
        <div className="flex gap-4">
          {(["full", "incremental"] as const).map((m) => (
            <label key={m} className="flex items-center gap-2 text-sm text-slate-300">
              <input
                type="radio"
                name="index-mode"
                value={m}
                checked={mode === m}
                onChange={() => setMode(m)}
                className="accent-sky-500"
              />
              {m === "full" ? t.indexing.full : t.indexing.incremental}
            </label>
          ))}
        </div>

        <label className="block text-xs font-medium text-slate-400">
          {t.indexing.directoryPath}
          <input
            type="text"
            value={directory}
            onChange={(e) => setDirectory(e.target.value)}
            placeholder={t.indexing.directoryPlaceholder}
            className={`mt-1 ${inputClass}`}
          />
        </label>

        <label className="block text-xs font-medium text-slate-400">
          {t.indexing.repoName}
          <input
            type="text"
            value={repository}
            onChange={(e) => setRepository(e.target.value)}
            placeholder={t.indexing.repoPlaceholder}
            className={`mt-1 ${inputClass}`}
          />
        </label>

        {mode === "incremental" && (
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-xs font-medium text-slate-400">
              {t.indexing.baseRef}
              <input
                type="text"
                value={baseRef}
                onChange={(e) => setBaseRef(e.target.value)}
                className={`mt-1 ${inputClass}`}
              />
            </label>
            <label className="block text-xs font-medium text-slate-400">
              {t.indexing.headRef}
              <input
                type="text"
                value={headRef}
                onChange={(e) => setHeadRef(e.target.value)}
                className={`mt-1 ${inputClass}`}
              />
            </label>
          </div>
        )}

        <button
          type="submit"
          disabled={mutation.isPending}
          className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:opacity-50"
        >
          {mutation.isPending && <Loader2 size={16} className="animate-spin" />}
          {mutation.isPending ? t.indexing.indexingInProgress : t.indexing.startIndexing}
        </button>
      </form>

      {mutation.data && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-emerald-400">{t.indexing.indexingResult}</h3>
          <JsonView data={mutation.data} />
        </div>
      )}
    </div>
  );
}
