import {
  CheckCircle2,
  Clock,
  Loader2,
  XCircle,
} from "lucide-react";

export const UPLOAD_EXT = [".java", ".py", ".go", ".js", ".ts", ".tsx", ".md", ".txt"] as const;

export const INPUT_CLASS =
  "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-300 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder-gray-500 dark:focus:border-sky-500 dark:focus:ring-sky-600";

export function isUploadableFileName(name: string): boolean {
  const n = name.toLowerCase();
  return UPLOAD_EXT.some((ext) => n.endsWith(ext));
}

export function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result ?? ""));
    fr.onerror = () => reject(fr.error ?? new Error("read failed"));
    fr.readAsText(file);
  });
}

export function phaseLabel(phase: string, t: Record<string, string>): string {
  const map: Record<string, string> = {
    scanning: t.phaseScan,
    indexing_code: t.phaseCode,
    indexing_docs: t.phaseDocs,
    indexing_and_enriching: t.phaseIndexingEnriching,
    enriching: t.phaseEnriching,
    embedding: t.phaseEmbedding,
    resolving_references: t.phaseRefs,
    completed: t.phaseComplete,
  };
  return map[phase] || phase;
}

export function enrichmentModeLabel(
  backend: string | undefined,
  t: Record<string, string>,
): string {
  if (backend === "gateway") return t.enrichmentGateway;
  if (backend === "direct") return t.enrichmentDirect;
  return t.enrichmentDisabled;
}

export function statusBadge(status: string, t: Record<string, string>) {
  const config: Record<string, { icon: typeof Clock; color: string; label: string }> = {
    pending: {
      icon: Clock,
      color: "text-gray-500 bg-gray-100 dark:bg-gray-800 dark:text-gray-400",
      label: t.taskPending,
    },
    running: {
      icon: Loader2,
      color: "text-sky-600 bg-sky-50 dark:bg-sky-950 dark:text-sky-400",
      label: t.taskRunning,
    },
    completed: {
      icon: CheckCircle2,
      color: "text-emerald-600 bg-emerald-50 dark:bg-emerald-950 dark:text-emerald-400",
      label: t.taskCompleted,
    },
    failed: {
      icon: XCircle,
      color: "text-red-600 bg-red-50 dark:bg-red-950 dark:text-red-400",
      label: t.taskFailed,
    },
  };
  const c = config[status] || config.pending;
  const Icon = c.icon;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${c.color}`}>
      <Icon size={12} className={status === "running" ? "animate-spin" : ""} />
      {c.label}
    </span>
  );
}
