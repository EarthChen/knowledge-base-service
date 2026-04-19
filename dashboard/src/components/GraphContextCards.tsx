import { useState, useMemo } from "react";
import { ChevronDown, Link2 } from "lucide-react";
import JsonView from "./JsonView";
import { useI18n } from "../i18n/context";

type Rel = "called_by" | "calls" | "method_of" | "subclass_of" | "business_flow" | string;

export interface GraphContextItem {
  name?: string;
  file?: string;
  line?: number;
  start_line?: number;
  end_line?: number;
  relationship?: Rel;
  source?: string;
  type?: string;
  data?: unknown;
  related_function?: string;
  [key: string]: unknown;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

function readNodeName(node: unknown): string {
  if (!isRecord(node)) return "";
  const props = node.properties;
  if (isRecord(props) && typeof props.name === "string") return props.name;
  if (typeof node.name === "string") return node.name;
  return "";
}

function fileLineRef(item: GraphContextItem): { file: string; line: number } {
  const file = String(item.file ?? "");
  const line = Number(
    item.start_line ?? item.line ?? 0,
  );
  return { file, line: Number.isFinite(line) ? line : 0 };
}

function CollapsibleSection({
  title,
  itemCount,
  children,
}: {
  title: string;
  itemCount: number;
  children: React.ReactNode;
}) {
  const defaultOpen = itemCount <= 5;
  const [open, setOpen] = useState(defaultOpen);
  if (itemCount === 0) return null;
  return (
    <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-2 bg-gray-50/80 px-3 py-2 text-left text-sm font-medium text-gray-800"
      >
        <span>
          {title}
          <span className="ml-2 text-xs font-normal text-gray-500">({itemCount})</span>
        </span>
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-gray-500 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && <div className="space-y-2 border-t border-gray-100 p-3">{children}</div>}
    </div>
  );
}

function TypeBadge({ rel }: { rel: string }) {
  return (
    <span className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase text-gray-600">
      {rel}
    </span>
  );
}

function FileLineButton({ file, line }: { file: string; line: number }) {
  const { t } = useI18n();
  const ref = file && line != null ? `${file}:${line}` : file || "—";
  return (
    <button
      type="button"
      title={t.search.graphContextCopyHint}
      onClick={() => {
        if (ref && ref !== "—") void navigator.clipboard.writeText(ref);
      }}
      className="max-w-[min(100%,18rem)] truncate text-left text-xs text-sky-600 underline decoration-sky-300/60 underline-offset-2 hover:text-sky-800"
    >
      {ref}
    </button>
  );
}

function groupItems(raw: unknown): {
  callChain: GraphContextItem[];
  methods: GraphContextItem[];
  inheritance: GraphContextItem[];
  businessFlow: GraphContextItem[];
  unknown: unknown[];
} {
  const list = Array.isArray(raw) ? raw : [];
  const callChain: GraphContextItem[] = [];
  const methods: GraphContextItem[] = [];
  const inheritance: GraphContextItem[] = [];
  const businessFlow: GraphContextItem[] = [];
  const unknown: unknown[] = [];

  for (const item of list) {
    if (!isRecord(item)) {
      unknown.push(item);
      continue;
    }
    const gi = item as GraphContextItem;
    if (gi.type === "business_flow") {
      businessFlow.push(gi);
      continue;
    }
    const rel = gi.relationship;
    if (rel === "called_by" || rel === "calls") callChain.push(gi);
    else if (rel === "method_of") methods.push(gi);
    else if (rel === "subclass_of") inheritance.push(gi);
    else unknown.push(item);
  }

  return { callChain, methods, inheritance, businessFlow, unknown };
}

export default function GraphContextCards({ items }: { items: unknown }) {
  const { t } = useI18n();
  const grouped = useMemo(() => groupItems(items), [items]);

  return (
    <div className="space-y-3">
      <CollapsibleSection title={t.search.graphSectionCallChain} itemCount={grouped.callChain.length}>
        {grouped.callChain.map((item, i) => {
          const { file, line } = fileLineRef(item);
          const src = String(item.source ?? "");
          const name = String(item.name ?? "");
          const rel = String(item.relationship ?? "");
          const left = rel === "called_by" ? src : name;
          const right = rel === "called_by" ? name : src;
          return (
            <div
              key={`cc-${i}`}
              className="flex flex-wrap items-center gap-2 rounded-md border border-gray-100 bg-gray-50/50 px-3 py-2 text-sm"
            >
              <span className="font-medium text-gray-900">{left || "?"}</span>
              <span className="text-gray-400" aria-hidden>
                →
              </span>
              <span className="font-medium text-gray-900">{right || "?"}</span>
              <TypeBadge rel={rel} />
              <FileLineButton file={file} line={line} />
            </div>
          );
        })}
      </CollapsibleSection>

      <CollapsibleSection title={t.search.graphSectionMethods} itemCount={grouped.methods.length}>
        {grouped.methods.map((item, i) => {
          const { file, line } = fileLineRef(item);
          const cls = String(item.source ?? "");
          const method = String(item.name ?? "");
          const display = cls && method ? `${cls}.${method}` : method || cls;
          return (
            <div
              key={`m-${i}`}
              className="flex flex-wrap items-center gap-2 rounded-md border border-gray-100 bg-gray-50/50 px-3 py-2 text-sm"
            >
              <code className="rounded bg-white px-1.5 py-0.5 text-xs text-gray-900">{display}</code>
              <TypeBadge rel="method_of" />
              <FileLineButton file={file} line={line} />
            </div>
          );
        })}
      </CollapsibleSection>

      <CollapsibleSection title={t.search.graphSectionInheritance} itemCount={grouped.inheritance.length}>
        {grouped.inheritance.map((item, i) => {
          const { file, line } = fileLineRef(item);
          const child = String(item.name ?? "");
          const parent = String(item.source ?? "");
          return (
            <div
              key={`in-${i}`}
              className="flex flex-wrap items-center gap-2 rounded-md border border-gray-100 bg-gray-50/50 px-3 py-2 text-sm"
            >
              <span className="font-medium text-gray-900">{child || "?"}</span>
              <span className="text-gray-400">→</span>
              <span className="text-gray-700">{parent || "?"}</span>
              <TypeBadge rel="subclass_of" />
              <FileLineButton file={file} line={line} />
            </div>
          );
        })}
      </CollapsibleSection>

      <CollapsibleSection title={t.search.graphSectionBusinessFlows} itemCount={grouped.businessFlow.length}>
        {grouped.businessFlow.map((item, i) => {
          const row = isRecord(item.data) ? item.data : {};
          const bf = row.bf ?? row.business_flow;
          const fn = row.f ?? row.function;
          const flowName = readNodeName(bf) || (isRecord(bf) ? String(bf.uid ?? "") : "") || "?";
          const fnName = readNodeName(fn);
          const related = String(item.related_function ?? "");
          return (
            <div
              key={`bf-${i}`}
              className="flex flex-wrap items-center gap-2 rounded-md border border-gray-100 bg-gray-50/50 px-3 py-2 text-sm"
            >
              <Link2 className="h-3.5 w-3.5 shrink-0 text-purple-500" />
              <span className="font-medium text-gray-900">{flowName}</span>
              {fnName ? (
                <>
                  <span className="text-gray-400">→</span>
                  <span className="text-gray-800">{fnName}</span>
                </>
              ) : null}
              {related ? (
                <span className="text-xs text-gray-500">
                  ({t.search.graphRelatedFn}: {related})
                </span>
              ) : null}
              <TypeBadge rel="business_flow" />
            </div>
          );
        })}
      </CollapsibleSection>

      {grouped.unknown.length > 0 ? (
        <div>
          <p className="mb-1 text-xs font-medium text-gray-500">{t.search.graphSectionOther}</p>
          <JsonView data={grouped.unknown} />
        </div>
      ) : null}
    </div>
  );
}
