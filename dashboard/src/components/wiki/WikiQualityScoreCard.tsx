import { useMemo, type CSSProperties } from "react";
import { Loader2 } from "lucide-react";
import { useWikiQualityScore } from "../../hooks/useWikiQualityScore";
import { useI18n } from "../../i18n/context";
import { getErrorMessage } from "../../utils/errorUtils";
import type { WikiQualityFactor } from "../../hooks/wikiTypes";

type Props = {
  businessId: string;
};

function scoreHue(score: number): string {
  if (score < 40) return "#dc2626";
  if (score < 70) return "#d97706";
  return "#059669";
}

function factorLabel(
  name: string,
  tw: {
    qualityFactorCoverage: string;
    qualityFactorStaleness: string;
    qualityFactorReferenceDensity: string;
    qualityFactorAnnotations: string;
  },
): string {
  switch (name) {
    case "coverage":
      return tw.qualityFactorCoverage;
    case "staleness":
      return tw.qualityFactorStaleness;
    case "reference_density":
      return tw.qualityFactorReferenceDensity;
    case "annotation_density":
      return tw.qualityFactorAnnotations;
    default:
      return name;
  }
}

export default function WikiQualityScoreCard({ businessId }: Props) {
  const { t } = useI18n();
  const q = useWikiQualityScore(businessId);

  const ringStyle = useMemo(() => {
    const s = q.data?.score ?? 0;
    const c = scoreHue(s);
    return {
      background: `conic-gradient(from -90deg, ${c} 0%, ${c} ${s}%, #e5e7eb ${s}%, #e5e7eb 100%)`,
    } as CSSProperties;
  }, [q.data?.score]);

  if (q.isLoading) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-gray-200 bg-white p-6 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-400">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        {t.common.loading}
      </div>
    );
  }

  if (q.isError) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50/80 p-4 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-200">
        {getErrorMessage(q.error, t.common.unexpectedError)}
      </div>
    );
  }

  const data = q.data;
  if (!data) return null;

  const score = data.score;
  const hue = scoreHue(score);
  const factors = (data.factors ?? []) as WikiQualityFactor[];

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">{t.wiki.qualityScoreTitle}</h3>

      <div className="mt-4 flex flex-col items-center gap-6 sm:flex-row sm:items-start sm:justify-center sm:gap-10">
        <div className="relative h-36 w-36 shrink-0" aria-hidden>
          <div className="absolute inset-0 rounded-full" style={ringStyle} />
          <div className="absolute inset-2 flex flex-col items-center justify-center rounded-full bg-white dark:bg-gray-900">
            <span className="text-3xl font-bold tabular-nums" style={{ color: hue }}>
              {score}
            </span>
            <span className="text-[10px] text-gray-500 dark:text-gray-400">/ 100</span>
          </div>
        </div>

        <ul className="w-full max-w-md space-y-3 text-sm">
          {factors.map((f) => (
            <li key={f.name}>
              <div className="mb-0.5 flex justify-between gap-2 text-xs">
                <span className="text-gray-600 dark:text-gray-400">
                  {factorLabel(f.name, t.wiki)}
                </span>
                <span className="tabular-nums text-gray-500 dark:text-gray-500">
                  {Math.round(f.score * 100)}%
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
                <div
                  className="h-full rounded-full transition-[width]"
                  style={{
                    width: `${Math.round(f.score * 100)}%`,
                    backgroundColor: scoreHue(Math.round(f.score * 100)),
                  }}
                />
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
