/**
 * Build dashboard URLs for the graph explorer.
 */

export function explorerGraphHref(entityUid: string, extraParams?: Record<string, string>): string {
  const sp = new URLSearchParams();
  sp.set("node", entityUid);
  if (extraParams) {
    for (const [k, v] of Object.entries(extraParams)) {
      if (v) sp.set(k, v);
    }
  }
  return `/explorer?${sp.toString()}`;
}
