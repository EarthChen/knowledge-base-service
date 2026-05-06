import type {
  WikiSemanticCallChainHit,
  WikiSemanticEntityHit,
  WikiSemanticWikiHit,
} from "../../hooks/wikiTypes";
import HighlightText from "../HighlightText";
import { wikiSearchOptionId } from "./WikiSearchResults";

type Props = {
  listboxId: string;
  wikiHits: WikiSemanticWikiHit[];
  entityHits: WikiSemanticEntityHit[];
  callChainHits: WikiSemanticCallChainHit[];
  /** Used when navigating to a wiki page (semantic wiki hits omit per-hit repository). */
  searchRepository: string;
  activeIndex: number;
  highlightQuery: string;
  onWikiSelect: (path: string, repository?: string) => void;
  sectionWiki: string;
  sectionEntities: string;
  sectionChains: string;
};

export function semanticSearchResultCount(
  wikiHits: WikiSemanticWikiHit[],
  entityHits: WikiSemanticEntityHit[],
  callChainHits: WikiSemanticCallChainHit[],
): number {
  return wikiHits.length + entityHits.length + callChainHits.length;
}

export default function WikiSemanticSearchResults({
  listboxId,
  wikiHits,
  entityHits,
  callChainHits,
  searchRepository,
  activeIndex,
  highlightQuery,
  onWikiSelect,
  sectionWiki,
  sectionEntities,
  sectionChains,
}: Props) {
  const hq = highlightQuery.trim();
  const showMark = Boolean(hq);
  let idx = -1;

  const nextId = () => {
    idx += 1;
    return wikiSearchOptionId(listboxId, idx);
  };

  return (
    <ul id={listboxId} className="max-h-80 overflow-y-auto py-1" role="listbox">
      {wikiHits.length > 0 && (
        <li role="presentation" className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
          {sectionWiki}
        </li>
      )}
      {wikiHits.map((r) => {
        const id = nextId();
        const flatIdx = idx;
        return (
          <li key={`w:${r.page_path}:${r.title}`} id={id} role="option" aria-selected={activeIndex === flatIdx}>
            <button
              type="button"
              tabIndex={-1}
              onClick={() => onWikiSelect(r.page_path, searchRepository)}
              className="flex w-full flex-col gap-0.5 px-3 py-2 text-left text-sm transition-colors hover:bg-sky-50 dark:hover:bg-sky-950/50"
            >
              <span className="font-medium text-gray-900 dark:text-gray-100">
                {showMark ? <HighlightText text={r.title} query={hq} /> : r.title}
              </span>
              <span className="truncate font-mono text-[11px] text-gray-500 dark:text-gray-400">
                {showMark ? <HighlightText text={r.page_path} query={hq} /> : r.page_path}
              </span>
              {r.snippet ? (
                <span className="line-clamp-2 text-xs text-gray-600 dark:text-gray-400">
                  {showMark ? <HighlightText text={r.snippet} query={hq} /> : r.snippet}
                </span>
              ) : null}
            </button>
          </li>
        );
      })}

      {entityHits.length > 0 && (
        <li role="presentation" className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
          {sectionEntities}
        </li>
      )}
      {entityHits.map((e) => {
        const id = nextId();
        const flatIdx = idx;
        return (
          <li key={`e:${e.repository}:${e.file_path}:${e.name}`} id={id} role="option" aria-selected={activeIndex === flatIdx}>
            <div className="flex w-full flex-col gap-0.5 px-3 py-2 text-left text-sm">
              <span className="font-medium text-gray-900 dark:text-gray-100">
                {showMark ? <HighlightText text={e.name} query={hq} /> : e.name}
              </span>
              <span className="text-[11px] text-gray-500 dark:text-gray-400">
                <span className="font-mono">{e.entity_type}</span>
                <span className="mx-1">·</span>
                <span className="font-mono">{e.repository}</span>
              </span>
              <span className="truncate font-mono text-[11px] text-gray-500 dark:text-gray-400">{e.file_path}</span>
              {e.summary ? (
                <span className="line-clamp-2 text-xs text-gray-600 dark:text-gray-400">
                  {showMark ? <HighlightText text={e.summary} query={hq} /> : e.summary}
                </span>
              ) : null}
            </div>
          </li>
        );
      })}

      {callChainHits.length > 0 && (
        <li role="presentation" className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
          {sectionChains}
        </li>
      )}
      {callChainHits.map((c) => {
        const id = nextId();
        const flatIdx = idx;
        const label = `${c.caller} → ${c.callee}`;
        return (
          <li key={`c:${c.caller}:${c.callee}:${c.relationship}`} id={id} role="option" aria-selected={activeIndex === flatIdx}>
            <div className="px-3 py-2 text-left text-sm text-gray-800 dark:text-gray-200">
              <span className="font-mono text-xs">
                {showMark ? <HighlightText text={label} query={hq} /> : label}
              </span>
              <span className="mt-0.5 block text-[11px] text-gray-500 dark:text-gray-400">{c.relationship}</span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
