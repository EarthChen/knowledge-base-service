import { Loader2, RefreshCw } from "lucide-react";
import { useWikiIncremental } from "../../hooks/useWikiIncremental";
import { useI18n } from "../../i18n/context";
import { useToast } from "../Toast";
import { getErrorMessage } from "../../utils/errorUtils";
import { ApiError } from "../../api/client";

type Props = { repository: string };

export default function WikiIncrementalTrigger({ repository }: Props) {
  const { t } = useI18n();
  const { toast } = useToast();
  const { mutate, isPending } = useWikiIncremental(repository);

  return (
    <button
      type="button"
      onClick={() =>
        mutate(undefined, {
          onSuccess: () => toast("success", t.wiki.repoIncrementalStarted),
          onError: (e) => {
            if (e instanceof ApiError) {
              toast("error", e.message);
            } else {
              toast("error", getErrorMessage(e, t.common.unexpectedError));
            }
          },
        })
      }
      disabled={isPending || !repository.trim()}
      className="inline-flex items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-medium text-blue-900 hover:bg-blue-100 disabled:opacity-50 dark:border-blue-900 dark:bg-blue-950/50 dark:text-blue-100 dark:hover:bg-blue-950"
      title={t.wiki.repoIncrementalTooltip}
    >
      {isPending ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <RefreshCw size={14} aria-hidden />}
      {t.wiki.repoIncrementalUpdate}
    </button>
  );
}
