import { useState } from "react";
import { Download } from "lucide-react";
import { apiDownload } from "../../api/client";
import { useI18n } from "../../i18n/context";

interface Props {
  repository: string;
  businessId: string;
}

export function OfflinePackDownloadButton({ repository, businessId }: Props) {
  const { t } = useI18n();
  const [loading, setLoading] = useState(false);
  const [truncated, setTruncated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleDownload = async () => {
    setLoading(true);
    setTruncated(false);
    try {
      setError(null);
      const resp = await apiDownload(
        `/wiki/${encodeURIComponent(repository)}/offline-pack?business_id=${encodeURIComponent(businessId)}`,
      );
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
      setError(t.wiki.offlinePackDownloadFailed);
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
        {loading ? t.wiki.offlinePackDownloading : t.wiki.offlinePackButton}
      </button>
      {error && <p className="text-xs text-red-500 mt-1">{error}</p>}
      {truncated && (
        <p className="mt-1 text-xs text-amber-600 dark:text-amber-500">{t.wiki.offlinePackDataTruncated}</p>
      )}
    </div>
  );
}
