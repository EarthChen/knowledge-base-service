import type { WikiDiagram } from "../../hooks/wikiTypes";
import { MermaidBlock } from "./MarkdownRenderer";

interface Props {
  diagrams: WikiDiagram[];
}

export function WikiDiagramSection({ diagrams }: Props) {
  const valid = diagrams.filter(
    (d) => d.content && d.content.trim().split("\n").length > 2,
  );
  if (valid.length === 0) return null;

  return (
    <section className="mt-6 space-y-4">
      {valid.map((d, i) => (
        <div
          key={`${d.diagram_type}-${i}`}
          className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900"
        >
          {d.title && (
            <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
              {d.title}
            </p>
          )}
          <MermaidBlock chart={d.content} />
        </div>
      ))}
    </section>
  );
}
