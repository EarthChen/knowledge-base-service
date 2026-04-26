import { useState, useCallback } from "react";
import { Search, Loader2 } from "lucide-react";

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
      const resp = await fetch("/api/v1/wiki/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: query, repository, business_id: businessId }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setResult(data);
      } else {
        let message = "Deep research is unavailable. It may be disabled on the server.";
        try {
          const data = (await resp.json()) as { detail?: unknown; message?: string };
          const d = data?.detail;
          if (typeof d === "string" && d.trim()) {
            message = d;
          } else if (typeof data?.message === "string" && data.message.trim()) {
            message = data.message;
          } else {
            message = `Request failed (${resp.status}). ${message}`;
          }
        } catch {
          message = `Request failed (${resp.status}). ${message}`;
        }
        setError(message);
      }
    } catch {
      setError("Network error. Check your connection and try again.");
    } finally {
      setLoading(false);
    }
  }, [query, loading, repository, businessId]);

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleResearch()}
          placeholder="Ask a deep research question..."
          className="flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
        />
        <button
          type="button"
          onClick={handleResearch}
          disabled={loading || !query.trim()}
          className="rounded-lg bg-blue-600 px-3 py-2 text-white hover:bg-blue-700 disabled:opacity-50"
          aria-label="Start research"
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
            <div key={i} className="rounded-lg border border-gray-100 p-3 dark:border-gray-800">
              <h4 className="mb-1 text-sm font-medium text-gray-700 dark:text-gray-300">{sq.question}</h4>
              <p className="text-sm text-gray-600 dark:text-gray-400">{sq.answer}</p>
            </div>
          ))}
          {result.synthesis && (
            <div className="mt-4 rounded-lg border border-blue-100 bg-blue-50/50 p-4 dark:border-blue-900 dark:bg-blue-950/20">
              <h4 className="mb-2 text-sm font-semibold text-blue-700 dark:text-blue-400">Synthesis</h4>
              <p className="whitespace-pre-wrap text-sm">{result.synthesis}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
