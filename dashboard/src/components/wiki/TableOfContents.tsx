import { useEffect, useMemo, useState } from "react";
import { useI18n } from "../../i18n/context";
import { parseMarkdownHeadings, type ParsedHeading } from "./headingUtils";

type Props = {
  content: string;
  /** When provided (e.g. from parent), skips parsing `content` again. */
  parsedHeadings?: ParsedHeading[];
};

export default function TableOfContents({ content, parsedHeadings }: Props) {
  const { t } = useI18n();
  const items = useMemo(
    () => parsedHeadings ?? parseMarkdownHeadings(content),
    [content, parsedHeadings],
  );
  const [activeId, setActiveId] = useState<string | null>(null);
  const highlightId = activeId ?? items[0]?.id ?? null;

  useEffect(() => {
    if (items.length === 0) return;

    const elements = items
      .map((item) => document.getElementById(item.id))
      .filter((el): el is HTMLElement => !!el);

    if (elements.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const intersecting = entries.filter((e) => e.isIntersecting);
        if (intersecting.length === 0) return;
        intersecting.sort(
          (a, b) => a.target.getBoundingClientRect().top - b.target.getBoundingClientRect().top,
        );
        setActiveId(intersecting[0]?.target.id ?? null);
      },
      {
        root: null,
        rootMargin: "-42% 0px -42% 0px",
        threshold: [0, 0.25, 0.5, 1],
      },
    );

    elements.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [items]);

  const scrollToId = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <nav aria-label={t.wiki.tocHeading} className="sticky top-6">
      <p className="mb-3 text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
        {t.wiki.tocHeading}
      </p>
      <ul className="max-h-[min(70vh,calc(100vh-10rem))] space-y-0.5 overflow-y-auto border-l border-gray-200 pl-3 text-xs text-gray-600 dark:border-gray-700 dark:text-gray-400">
        {items.map((item) => (
          <li key={item.id} style={{ paddingLeft: `${(item.level - 1) * 10}px` }}>
            <button
              type="button"
              onClick={() => scrollToId(item.id)}
              className={`block w-full rounded-md px-2 py-1 text-left transition-colors hover:bg-gray-100 hover:text-gray-900 dark:hover:bg-gray-800 dark:hover:text-gray-100 ${
                highlightId === item.id ? "bg-gray-100 font-medium text-gray-900 dark:bg-gray-800 dark:text-gray-100" : "text-gray-600 dark:text-gray-400"
              }`}
            >
              {item.text}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
