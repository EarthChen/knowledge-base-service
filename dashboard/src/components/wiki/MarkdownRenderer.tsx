import { useEffect, useId, useMemo, useRef } from "react";
import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import SourceLink from "./SourceLink";
import { parseMarkdownHeadings } from "./headingUtils";

function MermaidBlock({ chart }: { chart: string }) {
  const id = useId().replace(/:/g, "");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    let cancelled = false;
    void (async () => {
      const mermaid = await import("mermaid");
      if (cancelled) return;
      mermaid.default.initialize({
        startOnLoad: false,
        theme: "neutral",
        securityLevel: "strict",
      });
      el.removeAttribute("data-processed");
      el.textContent = chart;
      try {
        await mermaid.default.run({ nodes: [el] });
      } catch {
        el.innerHTML =
          `<pre class="rounded-lg bg-red-50 p-3 text-xs text-red-800">Mermaid failed to render</pre>`;
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [chart]);

  return (
    <div
      ref={ref}
      id={`mermaid-${id}`}
      className="mermaid my-4 overflow-x-auto rounded-xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900"
    />
  );
}

const MarkdownAnchor: Components["a"] = ({ href, children, className }) => {
  if (href?.startsWith("source://")) {
    return (
      <SourceLink href={href} className={className}>
        {children}
      </SourceLink>
    );
  }
  return (
    <a
      href={href}
      className={`font-medium text-sky-700 underline decoration-sky-300 underline-offset-2 hover:text-sky-900 dark:text-sky-400 dark:hover:text-sky-300 ${className ?? ""}`}
      target="_blank"
      rel="noreferrer noopener"
    >
      {children}
    </a>
  );
};

const MarkdownCode: Components["code"] = ({
  className,
  children,
  ...props
}) => {
  const match = /language-(\w+)/.exec(className ?? "");
  const lang = match?.[1];
  const text = String(children).replace(/\n$/, "");
  const isInline = !match && !/\r?\n/.test(text);

  if (match && lang === "mermaid") {
    return <MermaidBlock chart={text} />;
  }

  return (
    <code
      className={
        isInline
          ? "rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[0.9em] text-rose-800 dark:bg-gray-800 dark:text-rose-300"
          : `block overflow-x-auto rounded-lg bg-gray-900 p-4 font-mono text-sm text-gray-100 ${className ?? ""}`
      }
      {...props}
    >
      {children}
    </code>
  );
};

const MarkdownPre: Components["pre"] = ({ children }) => (
  <pre className="my-4 overflow-x-auto">{children}</pre>
);

type Props = {
  content: string;
};

export default function MarkdownRenderer({ content }: Props) {
  const headingIds = useMemo(
    () => parseMarkdownHeadings(content).map((h) => h.id),
    [content],
  );

  const components = useMemo<Components>(() => {
    let headingIndex = 0;
    function nextHeadingId() {
      return headingIds[headingIndex++];
    }

    const H1: Components["h1"] = ({ children, ...rest }) => (
      <h1 id={nextHeadingId()} className="scroll-mt-24" {...rest}>
        {children}
      </h1>
    );
    const H2: Components["h2"] = ({ children, ...rest }) => (
      <h2 id={nextHeadingId()} className="scroll-mt-24" {...rest}>
        {children}
      </h2>
    );
    const H3: Components["h3"] = ({ children, ...rest }) => (
      <h3 id={nextHeadingId()} className="scroll-mt-24" {...rest}>
        {children}
      </h3>
    );

    return {
      a: MarkdownAnchor,
      code: MarkdownCode,
      pre: MarkdownPre,
      h1: H1,
      h2: H2,
      h3: H3,
    };
  }, [headingIds]);

  return (
    <article className="prose prose-slate dark:prose-invert max-w-none prose-headings:scroll-mt-24 prose-a:text-sky-700 prose-pre:bg-transparent prose-pre:p-0 dark:prose-a:text-sky-400">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]} components={components}>
        {content}
      </ReactMarkdown>
    </article>
  );
}
