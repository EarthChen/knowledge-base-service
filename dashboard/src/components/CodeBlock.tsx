import { useSyncExternalStore } from "react";
import { Highlight, themes } from "prism-react-renderer";

function subscribeToDarkMode(cb: () => void) {
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  const observer = new MutationObserver(cb);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class"],
  });
  mq.addEventListener("change", cb);
  return () => {
    observer.disconnect();
    mq.removeEventListener("change", cb);
  };
}

function getIsDark() {
  return document.documentElement.classList.contains("dark");
}

function useIsDark() {
  return useSyncExternalStore(subscribeToDarkMode, getIsDark, () => false);
}

const EXT_TO_LANG: Record<string, string> = {
  py: "python",
  java: "java",
  go: "go",
  js: "javascript",
  jsx: "jsx",
  ts: "typescript",
  tsx: "tsx",
  md: "markdown",
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  xml: "markup",
  html: "markup",
  css: "css",
  sql: "sql",
  sh: "bash",
  bash: "bash",
};

function detectLanguage(filePath?: string): string {
  if (!filePath) return "python";
  const ext = filePath.split(".").pop()?.toLowerCase() ?? "";
  return EXT_TO_LANG[ext] ?? "python";
}

export default function CodeBlock({
  code,
  filePath,
  startLine,
}: {
  code: string;
  filePath?: string;
  startLine?: number;
}) {
  const language = detectLanguage(filePath);
  const lineOffset = (startLine ?? 1) - 1;
  const isDark = useIsDark();
  const theme = isDark ? themes.vsDark : themes.github;

  return (
    <Highlight theme={theme} code={code.trimEnd()} language={language}>
      {({ tokens, getLineProps, getTokenProps }) => (
        <pre className="max-h-80 overflow-auto text-xs leading-5">
          {tokens.map((line, i) => {
            const lineProps = getLineProps({ line });
            return (
              <div key={i} {...lineProps} className="table-row">
                <span className="table-cell select-none pr-4 text-right text-gray-400/60">
                  {i + 1 + lineOffset}
                </span>
                <span className="table-cell">
                  {line.map((token, key) => (
                    <span key={key} {...getTokenProps({ token })} />
                  ))}
                </span>
              </div>
            );
          })}
        </pre>
      )}
    </Highlight>
  );
}
