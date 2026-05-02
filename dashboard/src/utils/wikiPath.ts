export function encodeWikiPath(path: string): string {
  return path
    .split("/")
    .filter(Boolean)
    .map((seg) => encodeURIComponent(seg))
    .join("/");
}
