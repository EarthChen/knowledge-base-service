import { useState } from "react";
import { Download } from "lucide-react";
import { API_BASE, getCurrentBusiness, getToken } from "../../api/client";

interface Props {
  repository: string;
  businessId: string;
}

function packAuthHeaders(): Record<string, string> {
  const t = getToken();
  const biz = getCurrentBusiness();
  const h: Record<string, string> = {};
  if (t) h.Authorization = `Bearer ${t}`;
  if (biz) h["X-Business-Id"] = biz;
  return h;
}

export function OfflinePackDownloadButton({ repository, businessId }: Props) {
  const [loading, setLoading] = useState(false);
  const [truncated, setTruncated] = useState(false);

  const handleDownload = async () => {
    setLoading(true);
    setTruncated(false);
    try {
      const resp = await fetch(
        `${API_BASE}/wiki/${encodeURIComponent(repository)}/offline-pack?business_id=${encodeURIComponent(businessId)}`,
        { headers: packAuthHeaders() },
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data: unknown = await resp.json();
      const obj = data as { truncated?: boolean };
      if (obj.truncated) setTruncated(true);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${repository}-wiki-offline.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      /* network / parse */
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <button
        type="button"
        onClick={handleDownload}
        disabled={loading}
        className="flex items-center gap-1.5 rounded border px-3 py-1.5 text-sm hover:bg-gray-100 disabled:opacity-50 dark:hover:bg-gray-800"
        role="button"
      >
        <Download className="h-4 w-4" />
        {loading ? "Downloading..." : "Download Offline Pack"}
      </button>
      {truncated && <p className="mt-1 text-xs text-amber-600 dark:text-amber-500">Data truncated to 2000 pages</p>}
    </div>
  );
}
