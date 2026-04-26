/**
 * Mirrors `services/settings_service._flatten_settings` wiki branch + top-level keys
 * so PUT payloads use the category the API expects when a key is not yet in cached meta.
 */
export function getSettingCategory(key: string): string {
  const systemKeys = new Set(["host", "port", "log_level", "rate_limit_rpm", "require_auth"]);
  if (systemKeys.has(key)) return "system";
  if (key.startsWith("falkordb.")) return "storage";
  if (key.startsWith("embedding.")) return "embedding";
  if (key.startsWith("llm.")) return "llm";
  if (key.startsWith("wiki.")) {
    const fieldName = key.slice("wiki.".length);
    if (fieldName.includes("git")) return "wiki_git";
    if (
      fieldName.endsWith("_enabled") &&
      !["rag_", "enrichment_", "cot_", "code_budget_"].some((x) => fieldName.includes(x))
    ) {
      return "wiki_features";
    }
    return "wiki_generation";
  }
  return "system";
}
