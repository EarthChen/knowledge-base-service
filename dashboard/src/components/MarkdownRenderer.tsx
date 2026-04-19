import { useEffect, useMemo, useRef, useState, type ComponentPropsWithoutRef } from "react";
import { useI18n } from "../i18n/context";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import mermaid from "mermaid";

mermaid.initialize({
  startOnLoad: false,
  theme: "default",
  themeVariables: {
    darkMode: false,
    background: "#ffffff",
    primaryColor: "#dbeafe",
    primaryTextColor: "#1e293b",
    secondaryColor: "#e2e8f0",
    lineColor: "#94a3b8",
    textColor: "#334155",
    mainBkg: "#ffffff",
    nodeBorder: "#93c5fd",
    clusterBkg: "#f8fafc",
  },
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
});

let mermaidCounter = 0;

function DiagramModal({ svg, onClose }: { svg: string; onClose: () => void }) {
  const { t } = useI18n();
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "+" || e.key === "=") setScale((s) => Math.min(s + 0.25, 5));
      if (e.key === "-") setScale((s) => Math.max(s - 0.25, 0.25));
      if (e.key === "0") setScale(1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const handleWheel = (e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      setScale((s) => {
        const delta = e.deltaY > 0 ? -0.1 : 0.1;
        return Math.min(Math.max(s + delta, 0.25), 5);
      });
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm dark:bg-black/60"
      onClick={onClose}
    >
      <div
        className="relative flex h-[95vh] w-[95vw] flex-col overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-600 dark:bg-gray-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-gray-200 px-4 py-2 dark:border-gray-700">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setScale((s) => Math.max(s - 0.25, 0.25))}
              className="rounded px-2 py-1 text-sm text-gray-500 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
            >
              −
            </button>
            <span className="min-w-[4rem] text-center text-sm text-gray-700 dark:text-gray-300">
              {Math.round(scale * 100)}%
            </span>
            <button
              type="button"
              onClick={() => setScale((s) => Math.min(s + 0.25, 5))}
              className="rounded px-2 py-1 text-sm text-gray-500 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
            >
              +
            </button>
            <button
              type="button"
              onClick={() => setScale(1)}
              className="rounded px-2 py-1 text-xs text-gray-400 hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-200"
            >
              {t.common.diagramReset}
            </button>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-400 dark:text-gray-500">{t.common.diagramZoomHint}</span>
            <button
              type="button"
              onClick={onClose}
              className="rounded p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
            >
              ✕
            </button>
          </div>
        </div>
        <div
          className="flex-1 overflow-auto p-6"
          onWheel={handleWheel}
        >
          <div
            className="inline-block [&_svg]:block [&_svg]:max-w-none"
            style={{ width: `${scale * 100}%` }}
            dangerouslySetInnerHTML={{ __html: svg }}
          />
        </div>
      </div>
    </div>
  );
}

function MermaidBlock({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [modalOpen, setModalOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const id = `mermaid-${++mermaidCounter}`;

    mermaid
      .render(id, code.trim())
      .then(({ svg: rendered }) => {
        if (!cancelled) setSvg(rendered);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });

    return () => {
      cancelled = true;
    };
  }, [code]);

  if (error) {
    return (
      <pre className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
        {code}
      </pre>
    );
  }

  if (!svg) {
    return (
      <div className="flex items-center justify-center rounded-lg border border-gray-200 bg-gray-50 p-6 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-800/80 dark:text-gray-400">
        Rendering diagram…
      </div>
    );
  }

  return (
    <>
      <div
        ref={containerRef}
        className="group relative my-3 flex cursor-pointer justify-center overflow-x-auto rounded-lg border border-gray-200 bg-gray-50 p-4 transition-colors hover:border-sky-400 dark:border-gray-700 dark:bg-gray-800/60 dark:hover:border-sky-500 [&_svg]:max-w-full"
        onClick={() => setModalOpen(true)}
      >
        <div dangerouslySetInnerHTML={{ __html: svg }} />
        <div className="absolute right-2 top-2 rounded-md bg-gray-700/90 px-2 py-1 text-xs text-gray-100 opacity-0 transition-opacity group-hover:opacity-100">
          Click to zoom
        </div>
      </div>
      {modalOpen && <DiagramModal svg={svg} onClose={() => setModalOpen(false)} />}
    </>
  );
}

function CodeBlock({ className, children, node: _node, ...props }: ComponentPropsWithoutRef<"code"> & { node?: unknown }) {
  const match = /language-(\w+)/.exec(className || "");
  const lang = match?.[1];
  const codeStr = String(children).replace(/\n$/, "");

  if (lang === "mermaid") {
    return <MermaidBlock code={codeStr} />;
  }

  if (!match) {
    return (
      <code
        className="rounded-md border border-gray-200 bg-gray-100 px-1.5 py-0.5 text-[0.85em] text-sky-700 dark:border-gray-600 dark:bg-gray-800 dark:text-sky-300"
        {...props}
      >
        {children}
      </code>
    );
  }

  return (
    <pre className="my-3 overflow-x-auto rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm leading-relaxed dark:border-gray-700 dark:bg-gray-800/80">
      <code className={className} {...props}>
        {children}
      </code>
    </pre>
  );
}

const markdownComponents = {
  code: CodeBlock,
  a: ({ href, children, node: _node, ...props }: ComponentPropsWithoutRef<"a"> & { node?: unknown }) => {
    if (!href) return <span {...props}>{children}</span>;
    const isExternal = href.startsWith("http://") || href.startsWith("https://");
    return (
      <a
        href={href}
        target={isExternal ? "_blank" : "_self"}
        rel={isExternal ? "noopener noreferrer" : undefined}
        className="text-sky-600 underline decoration-sky-600/40 underline-offset-2 transition-colors hover:text-sky-500 hover:decoration-sky-500/60 dark:text-sky-400 dark:decoration-sky-500/40 dark:hover:text-sky-300 dark:hover:decoration-sky-400/60"
        {...props}
      >
        {children}
      </a>
    );
  },
  h1: ({ children, node: _, ...props }: ComponentPropsWithoutRef<"h1"> & { node?: unknown }) => (
    <h1 className="mb-4 mt-6 text-2xl font-bold text-gray-900 first:mt-0 dark:text-gray-100" {...props}>
      {children}
    </h1>
  ),
  h2: ({ children, node: _, ...props }: ComponentPropsWithoutRef<"h2"> & { node?: unknown }) => (
    <h2 className="mb-3 mt-5 text-xl font-semibold text-gray-900 first:mt-0 dark:text-gray-100" {...props}>
      {children}
    </h2>
  ),
  h3: ({ children, node: _, ...props }: ComponentPropsWithoutRef<"h3"> & { node?: unknown }) => (
    <h3 className="mb-2 mt-4 text-lg font-semibold text-gray-800 first:mt-0 dark:text-gray-100" {...props}>
      {children}
    </h3>
  ),
  h4: ({ children, node: _, ...props }: ComponentPropsWithoutRef<"h4"> & { node?: unknown }) => (
    <h4 className="mb-2 mt-3 text-base font-semibold text-gray-800 first:mt-0 dark:text-gray-200" {...props}>
      {children}
    </h4>
  ),
  p: ({ children, node: _, ...props }: ComponentPropsWithoutRef<"p"> & { node?: unknown }) => (
    <p className="mb-3 leading-relaxed text-gray-600 last:mb-0 dark:text-gray-400" {...props}>
      {children}
    </p>
  ),
  ul: ({ children, node: _, ...props }: ComponentPropsWithoutRef<"ul"> & { node?: unknown }) => (
    <ul className="mb-3 ml-6 list-disc space-y-1 text-gray-600 dark:text-gray-400" {...props}>
      {children}
    </ul>
  ),
  ol: ({ children, node: _, ...props }: ComponentPropsWithoutRef<"ol"> & { node?: unknown }) => (
    <ol className="mb-3 ml-6 list-decimal space-y-1 text-gray-600 dark:text-gray-400" {...props}>
      {children}
    </ol>
  ),
  li: ({ children, node: _, ...props }: ComponentPropsWithoutRef<"li"> & { node?: unknown }) => (
    <li className="leading-relaxed" {...props}>
      {children}
    </li>
  ),
  blockquote: ({ children, node: _, ...props }: ComponentPropsWithoutRef<"blockquote"> & { node?: unknown }) => (
    <blockquote
      className="my-3 border-l-4 border-sky-400 pl-4 text-gray-500 italic dark:border-sky-500 dark:text-gray-400"
      {...props}
    >
      {children}
    </blockquote>
  ),
  table: ({ children, node: _, ...props }: ComponentPropsWithoutRef<"table"> & { node?: unknown }) => (
    <div className="my-3 overflow-x-auto">
      <table className="w-full border-collapse text-sm" {...props}>
        {children}
      </table>
    </div>
  ),
  thead: ({ children, node: _, ...props }: ComponentPropsWithoutRef<"thead"> & { node?: unknown }) => (
    <thead className="border-b border-gray-300 text-left text-gray-700 dark:border-gray-600 dark:text-gray-300" {...props}>
      {children}
    </thead>
  ),
  th: ({ children, node: _, ...props }: ComponentPropsWithoutRef<"th"> & { node?: unknown }) => (
    <th className="px-3 py-2 font-semibold" {...props}>
      {children}
    </th>
  ),
  td: ({ children, node: _, ...props }: ComponentPropsWithoutRef<"td"> & { node?: unknown }) => (
    <td className="border-t border-gray-200 px-3 py-2 text-gray-500 dark:border-gray-700 dark:text-gray-400" {...props}>
      {children}
    </td>
  ),
  hr: ({ node: _, ...props }: ComponentPropsWithoutRef<"hr"> & { node?: unknown }) => (
    <hr className="my-6 border-gray-200 dark:border-gray-700" {...props} />
  ),
  img: ({ src, alt, node: _, ...props }: ComponentPropsWithoutRef<"img"> & { node?: unknown }) => (
    <img
      src={src}
      alt={alt}
      className="my-3 max-w-full rounded-lg border border-gray-200 dark:border-gray-700"
      loading="lazy"
      {...props}
    />
  ),
};

interface MarkdownRendererProps {
  content: string;
  className?: string;
  onDocLink?: (filePath: string) => void;
}

export default function MarkdownRenderer({ content, className = "", onDocLink }: MarkdownRendererProps) {
  const components = useMemo(() => {
    if (!onDocLink) return markdownComponents;

    return {
      ...markdownComponents,
      a: ({ href, children, node: _node, ...props }: ComponentPropsWithoutRef<"a"> & { node?: unknown }) => {
        if (!href) return <span {...props}>{children}</span>;
        const isExternal = href.startsWith("http://") || href.startsWith("https://") || href.startsWith("mailto:");
        const isDocLink = !isExternal && (href.endsWith(".md") || href.endsWith(".rst") || href.endsWith(".txt"));

        if (isDocLink) {
          return (
            <a
              href="#"
              onClick={(e) => {
                e.preventDefault();
                onDocLink(href);
              }}
              className="cursor-pointer text-sky-600 underline decoration-sky-600/40 underline-offset-2 transition-colors hover:text-sky-500 hover:decoration-sky-500/60 dark:text-sky-400 dark:decoration-sky-500/40 dark:hover:text-sky-300 dark:hover:decoration-sky-400/60"
              {...props}
            >
              {children}
            </a>
          );
        }

        return (
          <a
            href={href}
            target={isExternal ? "_blank" : "_self"}
            rel={isExternal ? "noopener noreferrer" : undefined}
            className="text-sky-600 underline decoration-sky-600/40 underline-offset-2 transition-colors hover:text-sky-500 hover:decoration-sky-500/60 dark:text-sky-400 dark:decoration-sky-500/40 dark:hover:text-sky-300 dark:hover:decoration-sky-400/60"
            {...props}
          >
            {children}
          </a>
        );
      },
    };
  }, [onDocLink]);

  return (
    <div className={`markdown-body ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
