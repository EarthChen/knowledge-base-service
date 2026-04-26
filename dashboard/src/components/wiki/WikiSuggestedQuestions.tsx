import { useState } from "react";
import { ChevronDown, ChevronUp, HelpCircle, MessageCircle } from "lucide-react";
import { useI18n } from "../../i18n/context";

interface WikiSuggestedQuestionsProps {
  questions: string[];
  onAskQuestion?: (question: string) => void;
}

export default function WikiSuggestedQuestions({
  questions,
  onAskQuestion,
}: WikiSuggestedQuestionsProps) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);

  if (questions.length === 0) return null;

  return (
    <section className="mt-8 border-t border-gray-100 pt-6 dark:border-gray-800">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        title={t.wiki.suggestedQuestionsToggle}
        className="flex w-full items-center justify-between gap-3 rounded-lg px-1 py-2 text-left hover:bg-gray-50/80 dark:hover:bg-gray-800/60"
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
          <HelpCircle size={18} className="text-sky-600 dark:text-sky-400" aria-hidden />
          {t.wiki.suggestedQuestionsTitle}
        </span>
        {expanded ? (
          <ChevronUp size={18} className="text-gray-500 dark:text-gray-400" />
        ) : (
          <ChevronDown size={18} className="text-gray-500 dark:text-gray-400" />
        )}
      </button>

      {expanded && (
        <ul className="mt-3 space-y-2">
          {questions.map((q, i) => (
            <li key={i}>
              <button
                type="button"
                onClick={() => onAskQuestion?.(q)}
                className="flex w-full items-start gap-3 rounded-lg border border-gray-100 bg-gray-50/50 px-4 py-3 text-left transition-colors hover:border-sky-200 hover:bg-sky-50/40 dark:border-gray-800 dark:bg-gray-800/30 dark:hover:border-sky-900 dark:hover:bg-sky-950/20"
              >
                <MessageCircle size={16} className="mt-0.5 shrink-0 text-sky-500" />
                <span className="text-sm text-gray-800 dark:text-gray-200">{q}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
