export function getErrorMessage(error: unknown, fallback?: string): string {
  if (error instanceof Error) {
    const m = error.message?.trim() ?? "";
    if (m && m !== "[object Object]") return error.message;
    return fallback ?? "";
  }
  if (typeof error === "string") return error;
  if (error && typeof error === "object" && "message" in error) {
    const m = (error as { message?: unknown }).message;
    if (typeof m === "string") return m;
  }
  return fallback ?? "";
}
