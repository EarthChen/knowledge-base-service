import { ExternalLink } from "lucide-react";

interface WikiEditButtonProps {
  gitRemoteUrl?: string;
  branch?: string;
  exportPath?: string;
}

function buildEditUrl(remote: string, branch: string, filePath: string): string | null {
  try {
    let base = remote.replace(/\.git$/, "");
    if (base.startsWith("git@")) {
      const rest = base.slice(4);
      const colon = rest.indexOf(":");
      if (colon === -1) return null;
      const host = rest.slice(0, colon);
      const pathPart = rest.slice(colon + 1);
      base = `https://${host}/${pathPart}`;
    }
    const url = new URL(`${base}/blob/${branch}/${filePath}`);
    if (url.protocol !== "https:") return null;
    return url.href;
  } catch {
    return null;
  }
}

export default function WikiEditButton({ gitRemoteUrl, branch, exportPath }: WikiEditButtonProps) {
  if (!gitRemoteUrl || !exportPath) return null;

  const editUrl = buildEditUrl(gitRemoteUrl, branch || "main", exportPath);
  if (!editUrl) return null;

  return (
    <a
      href={editUrl}
      target="_blank"
      rel="noreferrer noopener"
      className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 hover:text-gray-900 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-gray-100"
    >
      <ExternalLink size={12} />
      Edit on Git
    </a>
  );
}
