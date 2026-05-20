export const STALE_TIME = {
  REALTIME: 10_000, // 10s - health checks, active connections
  FAST: 30_000, // 30s - search results, wiki page content
  NORMAL: 60_000, // 60s - repo lists, business lists, graph stats
  SLOW: 5 * 60_000, // 5min - file tree, navigation tree
  STATIC: 30 * 60_000, // 30min - settings, schema info
} as const;
