const STORAGE_KEY = "kb_business_id";

export function getCurrentBusiness(): string {
  return localStorage.getItem(STORAGE_KEY) || "default";
}
