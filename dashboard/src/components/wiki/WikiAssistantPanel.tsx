import { useState } from "react";
import { useI18n } from "../../i18n/context";
import AskPanel from "./AskPanel";
import WikiEditPanel from "./WikiEditPanel";

type AssistantTab = "ask" | "edit";

interface Props {
  pageUid: string;
  currentContent: string;
  businessId: string;
  repository: string;
  pageContext?: string;
  onContentApplied?: (newContent: string) => void;
}

export default function WikiAssistantPanel({
  pageUid,
  currentContent,
  businessId,
  repository,
  pageContext,
  onContentApplied,
}: Props) {
  const { t } = useI18n();
  const ep = t.wiki.edit_panel;
  const [tab, setTab] = useState<AssistantTab>("ask");

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2" role="tablist" aria-label={ep.title}>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "ask"}
          onClick={() => setTab("ask")}
          className={`inline-flex rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
            tab === "ask"
              ? "bg-sky-100 text-sky-800 ring-1 ring-sky-200 dark:bg-sky-950 dark:text-sky-200 dark:ring-sky-800"
              : "text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
          }`}
        >
          {ep.tab_ask}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "edit"}
          onClick={() => setTab("edit")}
          className={`inline-flex rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
            tab === "edit"
              ? "bg-sky-100 text-sky-800 ring-1 ring-sky-200 dark:bg-sky-950 dark:text-sky-200 dark:ring-sky-800"
              : "text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
          }`}
        >
          {ep.tab_edit}
        </button>
      </div>

      {tab === "ask" ? (
        <AskPanel repository={repository} pageContext={pageContext} />
      ) : (
        <WikiEditPanel
          pageUid={pageUid}
          currentContent={currentContent}
          businessId={businessId}
          onContentApplied={onContentApplied}
        />
      )}
    </div>
  );
}
