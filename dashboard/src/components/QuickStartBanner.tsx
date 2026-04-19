import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Circle, Sparkles, X } from "lucide-react";
import { useI18n } from "../i18n/context";

const STORAGE_KEY = "kb_onboarding";

type OnboardingState = {
  dismissed?: boolean;
  completed?: Record<string, boolean>;
};

function readState(): OnboardingState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as OnboardingState;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writeState(next: OnboardingState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
}

export default function QuickStartBanner({ onDismiss }: { onDismiss: () => void }) {
  const { t } = useI18n();
  const [completed, setCompleted] = useState<Record<string, boolean>>({});

  useEffect(() => {
    const s = readState();
    setCompleted(s.completed ?? {});
  }, []);

  const persist = useCallback((nextCompleted: Record<string, boolean>) => {
    const s = readState();
    writeState({ ...s, completed: nextCompleted });
    setCompleted(nextCompleted);
  }, []);

  const steps = useMemo(
    () =>
      [
        {
          id: "index",
          label: `① ${t.overview.quickStartStepIndex}`,
          to: "/indexing",
        },
        {
          id: "search",
          label: `② ${t.overview.quickStartStepSearch}`,
          to: "/search",
        },
        {
          id: "wiki",
          label: `③ ${t.overview.quickStartStepWiki}`,
          to: "/wiki",
        },
        {
          id: "ask",
          label: `④ ${t.overview.quickStartStepAsk}`,
          to: "/wiki?focus=ask",
        },
      ] as const,
    [t],
  );

  const markDone = useCallback(
    (id: string) => {
      persist({ ...completed, [id]: true });
    },
    [completed, persist],
  );

  const handleDismiss = useCallback(() => {
    const s = readState();
    writeState({ ...s, dismissed: true });
    onDismiss();
  }, [onDismiss]);

  return (
    <div className="relative overflow-hidden rounded-xl border border-sky-200/90 bg-gradient-to-br from-sky-50 via-white to-indigo-50/80 px-4 py-4 shadow-sm">
      <button
        type="button"
        onClick={handleDismiss}
        className="absolute right-3 top-3 rounded-lg p-1 text-gray-400 transition-colors hover:bg-white/80 hover:text-gray-700"
        aria-label={t.overview.quickStartDismiss}
      >
        <X size={18} />
      </button>

      <div className="flex flex-wrap items-start gap-3 pr-10">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-sky-100 text-sky-700">
          <Sparkles size={20} aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-gray-900">{t.overview.quickStartTitle}</h3>
          <p className="mt-1 text-xs text-gray-600">{t.overview.quickStartSubtitle}</p>

          <ul className="mt-4 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:gap-x-4 sm:gap-y-2">
            {steps.map((step) => {
              const done = Boolean(completed[step.id]);
              return (
                <li key={step.id}>
                  <Link
                    to={step.to}
                    onClick={() => markDone(step.id)}
                    className="group inline-flex items-center gap-2 rounded-lg border border-transparent px-2 py-1.5 text-xs font-medium text-sky-800 transition-colors hover:border-sky-200 hover:bg-white/70"
                  >
                    {done ? (
                      <CheckCircle2 size={16} className="shrink-0 text-emerald-600" aria-hidden />
                    ) : (
                      <Circle size={16} className="shrink-0 text-sky-400" aria-hidden />
                    )}
                    <span className="underline-offset-2 group-hover:underline">{step.label}</span>
                  </Link>
                </li>
              );
            })}
          </ul>

          <button
            type="button"
            onClick={handleDismiss}
            className="mt-3 text-xs font-medium text-gray-500 underline-offset-2 hover:text-gray-800 hover:underline"
          >
            {t.overview.quickStartDismiss}
          </button>
        </div>
      </div>
    </div>
  );
}
