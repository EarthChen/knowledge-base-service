import { useEffect, useRef, useState } from "react";
import FocusTrap from "../FocusTrap";
import { useI18n } from "../../i18n/context";
import WikiDiffViewer from "./WikiDiffViewer";
import WikiVersionBadge from "./WikiVersionBadge";
import WikiVersionHistory from "./WikiVersionHistory";

export function WikiVersionPicker({
  businessId,
  pageUid,
  version,
  generatedAt,
}: {
  businessId: string;
  pageUid: string;
  version: string;
  generatedAt: string;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [diffVersions, setDiffVersions] = useState<{ from: number; to: number } | null>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || !pageUid) return;
    const id = setTimeout(() => {
      if (popoverRef.current && !popoverRef.current.contains(document.activeElement as Node | null)) {
        popoverRef.current.focus();
      }
    }, 0);
    return () => clearTimeout(id);
  }, [open, pageUid]);

  return (
    <div className="relative inline-block align-middle">
      <WikiVersionBadge
        version={Number(version)}
        generatedAt={generatedAt}
        onClick={pageUid ? () => setOpen((o) => !o) : undefined}
      />
      {open && pageUid ? (
        <FocusTrap onEscape={() => setOpen(false)}>
          <div
            ref={popoverRef}
            tabIndex={-1}
            className="absolute left-0 top-full z-50 mt-2 max-h-[min(70vh,520px)] w-[min(calc(100vw-2rem),36rem)] overflow-y-auto rounded-xl border border-gray-200 bg-white p-4 shadow-xl outline-none dark:border-gray-700 dark:bg-gray-900"
          >
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-600 dark:text-gray-400">
              {t.wiki.versionHistoryTitle}
            </h4>
            <WikiVersionHistory
              businessId={businessId}
              pageUid={pageUid}
              onSelectVersions={(from, to) => setDiffVersions({ from, to })}
            />
            {diffVersions ? (
              <div className="mt-4">
                <WikiDiffViewer
                  businessId={businessId}
                  pageUid={pageUid}
                  fromVersion={diffVersions.from}
                  toVersion={diffVersions.to}
                  onClose={() => setDiffVersions(null)}
                />
              </div>
            ) : null}
          </div>
        </FocusTrap>
      ) : null}
    </div>
  );
}
