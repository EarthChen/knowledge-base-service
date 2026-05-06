import {
  lazy,
  Suspense,
  useEffect,
  useId,
  useMemo,
  useRef,
  type AnchorHTMLAttributes,
  type ReactNode,
} from "react";
import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { useI18n } from "../../i18n/context";
import SourceLink from "./SourceLink";
import { parseMarkdownHeadings, type ParsedHeading } from "./headingUtils";
import { replaceWikilinksWithHtml } from "./wikilinkParser";
import WikiLinkPreview from "./WikiLinkPreview";
import { getMermaid } from "./mermaidLoader";

const LazyCodeBlock = lazy(() => import("./CodeBlock"));

export function MermaidBlock({ chart }: { chart: string }) {
  const { t } = useI18n();
  const id = useId().replace(/:/g, "");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    let cancelled = false;
    void (async () => {
      const mermaid = await getMermaid();
      if (cancelled) return;
      el.removeAttribute("data-processed");
      el.textContent = chart;
      try {
        await mermaid.run({ nodes: [el] });
      } catch {
        const msg = t.common.mermaidRenderFailed;
        el.innerHTML = `<pre class="rounded-lg bg-red-50 p-3 text-xs text-red-800"></pre>`;
        const pre = el.querySelector("pre");
        if (pre) pre.textContent = msg;
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [chart, t.common.mermaidRenderFailed]);

  return (
    <div
      ref={ref}
      id={`mermaid-${id}`}
      className="mermaid my-4 overflow-x-auto rounded-xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900"
    />
  );
}

const sanitizeSchema = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames ?? []), "wikilink"],
  attributes: {
    ...defaultSchema.attributes,
    wikilink: ["data-path"],
  },
};

function MarkdownAnchor({
  href,
  children,
  className,
  onDocLink,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement> & { onDocLink?: (filePath: string) => void }) {
  if (onDocLink && href) {
    const isExternal = href.startsWith("http://") || href.startsWith("https://") || href.startsWith("mailto:");
    const isDocLink =
      !isExternal && (href.endsWith(".md") || href.endsWith(".rst") || href.endsWith(".txt"));
    if (isDocLink) {
      return (
        <a
          href="#"
          onClick={(e) => {
            e.preventDefault();
            onDocLink(href);
          }}
          className={`font-medium text-sky-700 underline decoration-sky-300 underline-offset-2 hover:text-sky-900 dark:text-sky-400 dark:hover:text-sky-300 ${className ?? ""}`}
          {...props}
        >
          {children}
        </a>
      );
    }
  }
  if (href) {
    const SAFE_SCHEMES = /^(https?:|mailto:|#|\/|source:\/\/)/i;
    if (!SAFE_SCHEMES.test(href)) {
      return <span>{children}</span>;
    }
  }
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
      {...props}
    >
      {children}
    </a>
  );
}

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

  if (isInline) {
    return (
      <code
        className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[0.9em] text-rose-800 dark:bg-gray-800 dark:text-rose-300"
        {...props}
      >
        {children}
      </code>
    );
  }

  return (
    <Suspense
      fallback={
        <pre className="overflow-x-auto rounded-lg bg-gray-900 p-4 font-mono text-sm text-gray-100">
          {text}
        </pre>
      }
    >
      <LazyCodeBlock lang={lang || "text"} text={text} />
    </Suspense>
  );
};

const MarkdownPre: Components["pre"] = ({ children }) => (
  <div className="my-4 overflow-x-auto">{children}</div>
);

type Props = {
  content: string;
  businessId?: string;
  wikiLinkParams?: Record<string, string>;
  /** When provided (e.g. from parent TOC), avoids a second `parseMarkdownHeadings` pass. */
  headings?: ParsedHeading[];
  /** Resolve relative .md / .rst / .txt links (e.g. knowledge documents tree). */
  onDocLink?: (filePath: string) => void;
};

export default function MarkdownRenderer({
  content,
  businessId = "",
  wikiLinkParams,
  headings,
  onDocLink,
}: Props) {
  const headingIds = useMemo(() => (headings ?? parseMarkdownHeadings(content)).map((h) => h.id), [content, headings]);

  const processedContent = useMemo(() => {
    const withSourceLinks = content.replace(
      /`(source:\/\/[^`]+)`/g,
      (_match, uri: string) => `[${uri}](${uri})`,
    );
    return replaceWikilinksWithHtml(withSourceLinks);
  }, [content]);

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
      a: (({ node: _node, ...props }) => (
        <MarkdownAnchor {...props} onDocLink={onDocLink} />
      )) as Components["a"],
      code: MarkdownCode,
      pre: MarkdownPre,
      h1: H1,
      h2: H2,
      h3: H3,
      wikilink: ({
        "data-path": dataPath,
        children,
      }: {
        "data-path"?: string;
        children?: ReactNode;
      }) => {
        const path = dataPath ? decodeURIComponent(dataPath) : "";
        if (!path) return <span>{children}</span>;
        return (
          <WikiLinkPreview path={path} businessId={businessId} wikiLinkParams={wikiLinkParams}>
            {children}
          </WikiLinkPreview>
        );
      },
    };
  }, [headingIds, businessId, wikiLinkParams, onDocLink]);

  return (
    <article className="prose prose-slate dark:prose-invert max-w-none break-words prose-headings:scroll-mt-24 prose-a:text-sky-700 prose-pre:bg-transparent prose-pre:p-0 dark:prose-a:text-sky-400">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, [rehypeSanitize, sanitizeSchema]]}
        components={components}
      >
        {processedContent}
      </ReactMarkdown>
    </article>
  );
}
