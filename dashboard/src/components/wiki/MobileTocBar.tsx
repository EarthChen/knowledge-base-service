import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import type { ParsedHeading } from "./headingUtils";
import TableOfContents from "./TableOfContents";

type Props = {
  content: string;
  heading: string;
  parsedHeadings: ParsedHeading[];
};

export default function MobileTocBar({ content, heading, parsedHeadings }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <div className="shrink-0 border-b border-gray-100 px-5 py-3 dark:border-gray-700 lg:hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 rounded-lg border border-gray-200 bg-gray-50/90 px-3 py-2 text-left text-sm font-medium text-gray-800 transition-colors hover:bg-gray-100 dark:border-gray-600 dark:bg-gray-800/70 dark:text-gray-100 dark:hover:bg-gray-800"
      >
        {heading}
        {open ? (
          <ChevronUp size={18} className="shrink-0 text-gray-500 dark:text-gray-400" aria-hidden />
        ) : (
          <ChevronDown size={18} className="shrink-0 text-gray-500 dark:text-gray-400" aria-hidden />
        )}
      </button>
      <div
        className={`grid transition-[grid-template-rows] duration-200 ease-out ${
          open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        }`}
      >
        <div className="min-h-0 overflow-hidden">
          <div className="border-t border-gray-100 pt-3 dark:border-gray-700">
            <TableOfContents content={content} parsedHeadings={parsedHeadings} />
          </div>
        </div>
      </div>
    </div>
  );
}
