let mermaidPromise: Promise<typeof import("mermaid").default> | null = null;

/**
 * Lazy-loads mermaid, initializes it once, and reuses the same instance
 * for every diagram block in the app.
 */
export function getMermaid(): Promise<typeof import("mermaid").default> {
  if (!mermaidPromise) {
    mermaidPromise = (async () => {
      const mod = await import("mermaid");
      const m = mod.default;
      m.initialize({
        startOnLoad: false,
        theme: "neutral",
        securityLevel: "loose",
      });
      return m;
    })();
  }
  return mermaidPromise;
}
