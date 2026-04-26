import { useState, useCallback } from "react";
import { Search, Loader2 } from "lucide-react";
import { api, ApiError } from "../../api/client";
import { useI18n } from "../../i18n/context";

type ResearchResult = {
  question: string;
  sub_questions: Array<{ question: string; answer: string }>;
  synthesis: string;
};

type Props = {
  businessId: string;
  repository: string;
};

export default function DeepResearchPanel({ businessId, repository }: Props) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleResearch = useCallback(async () => {
    if (!query.trim() || loading) return;
    setLoading(true);
    setResult(null);
    setError(null);
    try {
      const data = await api<ResearchResult>("/wiki/research", {
        method: "POST",
        body: JSON.stringify({ question: query, repository, business_id: businessId }),
      });
      setResult(data);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(e.message?.trim() || t.wiki.deepResearchError);
      } else {
        setError(t.wiki.deepResearchNetworkError);
      }
    } finally {
      setLoading(false);
    }
  }, [query, loading, repository, businessId, t]);

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleResearch()}
          placeholder={t.wiki.deepResearchPlaceholder}
          className="flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
        />
        <button
          type="button"
          onClick={handleResearch}
          disabled={loading || !query.trim()}
          className="rounded-lg bg-blue-600 px-3 py-2 text-white hover:bg-blue-700 disabled:opacity-50"
          aria-label={t.wiki.deepResearchStart}
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
        </button>
      </div>

      {error && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100">
          {error}
        </p>
      )}

      {result && (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold">{result.question}</h3>
          {result.sub_questions.map((sq, i) => (
            <div
              key={i}
              className="rounded-lg border border-gray-100 p-3 dark:border-gray-800"
              aria-label={`${t.wiki.deepResearchFinding} ${i + 1}`}
            >
              <h4 className="mb-1 text-sm font-medium text-gray-700 dark:text-gray-300">{sq.question}</h4>
              <p className="text-sm text-gray-600 dark:text-gray-400">{sq.answer}</p>
            </div>
          ))}
          {result.synthesis && (
            <div className="mt-4 rounded-lg border border-blue-100 bg-blue-50/50 p-4 dark:border-blue-900 dark:bg-blue-950/20">
              <h4 className="mb-2 text-sm font-semibold text-blue-700 dark:text-blue-400">
                {t.wiki.deepResearchSynthesis}
              </h4>
              <p className="whitespace-pre-wrap text-sm">{result.synthesis}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
