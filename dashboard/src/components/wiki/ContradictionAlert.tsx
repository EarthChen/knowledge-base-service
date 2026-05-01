import { useI18n } from "../../i18n/context";

type Props = {
  unresolvedCount: number;
  summary?: string;
};

/** Yellow warning when the page is involved in unresolved wiki contradictions. */
export function ContradictionAlert({ unresolvedCount, summary }: Props) {
  const { t } = useI18n();
  if (unresolvedCount < 1) return null;
  return (
    <div className="border-l-4 border-amber-400 bg-amber-50 px-4 py-3 text-amber-900 dark:border-amber-500 dark:bg-amber-950/40 dark:text-amber-100">
      <strong>{t.wiki.contradiction_alert.title}</strong>
      <p className="mt-0.5 text-sm">
        {t.wiki.contradiction_alert.description.replace("{count}", String(unresolvedCount))}
      </p>
      {summary ? <p className="mt-1 text-sm opacity-90">{summary}</p> : null}
    </div>
  );
}
