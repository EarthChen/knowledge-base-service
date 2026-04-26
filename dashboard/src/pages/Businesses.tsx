import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, Plus, Trash2 } from "lucide-react";
import { api } from "../api/client";
import type { Business, BusinessesResponse } from "../api/types";
import { useI18n } from "../i18n/context";
import { getErrorMessage } from "../utils/errorUtils";
import { useBusiness } from "../contexts/BusinessContext";
import { useAuth } from "../contexts/AuthContext";
import { useToast } from "../components/Toast";

export default function Businesses() {
  const { t } = useI18n();
  const { currentBusiness, setCurrentBusiness } = useBusiness();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery<BusinessesResponse>({
    queryKey: ["businesses"],
    queryFn: () => api("/businesses", { method: "GET" }),
    staleTime: 60_000,
  });
  const createMut = useMutation<Business, Error, { id: string; name: string; description: string }>(
    {
      mutationFn: (body) =>
        api("/businesses", { method: "POST", body: JSON.stringify(body) }),
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: ["businesses"] });
      },
    },
  );
  const deleteMut = useMutation<{ deleted: string }, Error, string>({
    mutationFn: (id) =>
      api(`/businesses/${encodeURIComponent(id)}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["businesses"] });
    },
  });
  const { toast } = useToast();
  const { isAdmin } = useAuth();

  const [showForm, setShowForm] = useState(false);
  const [formId, setFormId] = useState("");
  const [formName, setFormName] = useState("");
  const [formDesc, setFormDesc] = useState("");

  const handleCreate = async () => {
    if (!formId.trim() || !formName.trim()) return;
    try {
      await createMut.mutateAsync({
        id: formId.trim(),
        name: formName.trim(),
        description: formDesc.trim(),
      });
      toast("success", t.businesses.created);
      setFormId("");
      setFormName("");
      setFormDesc("");
      setShowForm(false);
    } catch (err: unknown) {
      toast("error", getErrorMessage(err, t.common.unexpectedError) || t.businesses.createFailed);
    }
  };

  const handleDelete = async (id: string) => {
    const yes = window.confirm(t.businesses.deleteConfirm.replace("{id}", id));
    if (!yes) return;
    try {
      await deleteMut.mutateAsync(id);
      toast("success", t.businesses.deleted.replace("{id}", id));
      if (currentBusiness === id) {
        setCurrentBusiness("default");
      }
    } catch (err: unknown) {
      toast("error", getErrorMessage(err, t.common.unexpectedError) || t.businesses.deleteFailed);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{t.businesses.title}</h2>
        {isAdmin && (
          <button
            onClick={() => setShowForm(!showForm)}
            className="flex items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 transition-colors"
          >
            <Plus size={16} />
            {t.businesses.create}
          </button>
        )}
      </div>

      {showForm && (
        <div className="space-y-4 rounded-xl border border-gray-300 bg-gray-50 p-5 dark:border-gray-600 dark:bg-gray-800/50">
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">
              {t.businesses.idLabel}
            </label>
            <input
              value={formId}
              onChange={(e) => setFormId(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""))}
              placeholder={t.businesses.idPlaceholder}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-sky-400 focus:outline-none focus:ring-1 focus:ring-sky-300 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 dark:placeholder-gray-500 dark:focus:border-sky-500 dark:focus:ring-sky-600"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">
              {t.businesses.nameLabel}
            </label>
            <input
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              placeholder={t.businesses.namePlaceholder}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-sky-400 focus:outline-none focus:ring-1 focus:ring-sky-300 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 dark:placeholder-gray-500 dark:focus:border-sky-500 dark:focus:ring-sky-600"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-500 dark:text-gray-400">
              {t.businesses.descLabel}
            </label>
            <input
              value={formDesc}
              onChange={(e) => setFormDesc(e.target.value)}
              placeholder={t.businesses.descPlaceholder}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-sky-400 focus:outline-none focus:ring-1 focus:ring-sky-300 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 dark:placeholder-gray-500 dark:focus:border-sky-500 dark:focus:ring-sky-600"
            />
          </div>
          <div className="flex gap-3">
            <button
              onClick={handleCreate}
              disabled={createMut.isPending || !formId.trim() || !formName.trim()}
              className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50 transition-colors"
            >
              {createMut.isPending ? t.businesses.creating : t.businesses.create}
            </button>
            <button
              onClick={() => setShowForm(false)}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
            >
              {t.businesses.cancel}
            </button>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="text-sm text-gray-400 dark:text-gray-500">{t.common.loading}</div>
      ) : !data?.businesses?.length ? (
        <div className="rounded-xl border border-gray-200 p-8 text-center text-sm text-gray-400 dark:border-gray-700 dark:text-gray-500">
          {t.businesses.empty}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.businesses.map((biz) => (
            <div
              key={biz.id}
              className={`group relative rounded-xl border p-5 transition-colors ${
                currentBusiness === biz.id
                  ? "border-sky-400 bg-sky-50 dark:border-sky-600 dark:bg-sky-950/40"
                  : "border-gray-200 bg-white hover:border-gray-300 dark:border-gray-700 dark:bg-gray-900 dark:hover:border-gray-600"
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div
                    className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                      currentBusiness === biz.id
                        ? "bg-sky-50 text-sky-700 dark:bg-sky-950/60 dark:text-sky-400"
                        : "bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400"
                    }`}
                  >
                    <Building2 size={20} />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">{biz.name}</h3>
                    <p className="text-xs text-gray-400 dark:text-gray-500">{biz.id}</p>
                  </div>
                </div>
                {isAdmin && biz.id !== "default" && (
                  <button
                    onClick={() => handleDelete(biz.id)}
                    className="rounded p-1 text-gray-500 opacity-0 transition-all hover:bg-red-50 hover:text-red-600 group-hover:opacity-100 dark:text-gray-400 dark:hover:bg-red-950/50 dark:hover:text-red-400"
                    title={t.businesses.deleteBtn}
                  >
                    <Trash2 size={16} />
                  </button>
                )}
              </div>
              {biz.description && (
                <p className="mt-3 line-clamp-2 text-xs text-gray-500 dark:text-gray-400">
                  {biz.description}
                </p>
              )}
              <div className="mt-4 flex items-center justify-between">
                <span className="text-[11px] text-gray-500 dark:text-gray-400">
                  {new Date(biz.created_at * 1000).toLocaleDateString()}
                </span>
                {currentBusiness === biz.id ? (
                  <span className="rounded-full bg-sky-50 px-2.5 py-0.5 text-[11px] font-medium text-sky-700 dark:bg-sky-950/60 dark:text-sky-400">
                    {t.businesses.current}
                  </span>
                ) : (
                  <button
                    onClick={() => setCurrentBusiness(biz.id)}
                    className="rounded-full border border-gray-300 px-2.5 py-0.5 text-[11px] text-gray-500 transition-colors hover:border-sky-400 hover:text-sky-600 dark:border-gray-600 dark:text-gray-400 dark:hover:border-sky-500 dark:hover:text-sky-400"
                  >
                    {t.businesses.switchTo}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
