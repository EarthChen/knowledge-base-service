import { useState } from "react";
import { Building2, Plus, Trash2 } from "lucide-react";
import { useBusinesses, useCreateBusiness, useDeleteBusiness } from "../api/hooks";
import { useI18n } from "../i18n/context";
import { useBusiness } from "../contexts/BusinessContext";
import { useAuth } from "../contexts/AuthContext";
import { useToast } from "../components/Toast";

export default function Businesses() {
  const { t } = useI18n();
  const { currentBusiness, setCurrentBusiness } = useBusiness();
  const { data, isLoading } = useBusinesses();
  const createMut = useCreateBusiness();
  const deleteMut = useDeleteBusiness();
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
      toast("error", String((err as Error).message || t.businesses.createFailed));
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
      toast("error", String((err as Error).message || t.businesses.deleteFailed));
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">{t.businesses.title}</h2>
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
        <div className="rounded-xl border border-gray-300 bg-gray-50 p-5 space-y-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-500">
              {t.businesses.idLabel}
            </label>
            <input
              value={formId}
              onChange={(e) => setFormId(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""))}
              placeholder="team-alpha"
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-sky-400 focus:outline-none focus:ring-1 focus:ring-sky-300"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-500">
              {t.businesses.nameLabel}
            </label>
            <input
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              placeholder="Team Alpha"
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-sky-400 focus:outline-none focus:ring-1 focus:ring-sky-300"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-500">
              {t.businesses.descLabel}
            </label>
            <input
              value={formDesc}
              onChange={(e) => setFormDesc(e.target.value)}
              placeholder={t.businesses.descPlaceholder}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-sky-400 focus:outline-none focus:ring-1 focus:ring-sky-300"
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
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-500 hover:bg-gray-100 hover:text-gray-900 transition-colors"
            >
              {t.businesses.cancel}
            </button>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="text-sm text-gray-400">Loading...</div>
      ) : !data?.businesses?.length ? (
        <div className="rounded-xl border border-gray-200 p-8 text-center text-sm text-gray-400">
          {t.businesses.empty}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.businesses.map((biz) => (
            <div
              key={biz.id}
              className={`group relative rounded-xl border p-5 transition-colors ${
                currentBusiness === biz.id
                  ? "border-sky-400 bg-sky-50"
                  : "border-gray-200 bg-white hover:border-gray-300"
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div
                    className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                      currentBusiness === biz.id
                        ? "bg-sky-50 text-sky-700"
                        : "bg-gray-100 text-gray-500"
                    }`}
                  >
                    <Building2 size={20} />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-gray-900">{biz.name}</h3>
                    <p className="text-xs text-gray-400">{biz.id}</p>
                  </div>
                </div>
                {isAdmin && biz.id !== "default" && (
                  <button
                    onClick={() => handleDelete(biz.id)}
                    className="rounded p-1 text-gray-500 opacity-0 hover:bg-red-50 hover:text-red-600 group-hover:opacity-100 transition-all"
                    title={t.businesses.deleteBtn}
                  >
                    <Trash2 size={16} />
                  </button>
                )}
              </div>
              {biz.description && (
                <p className="mt-3 text-xs text-gray-500 line-clamp-2">
                  {biz.description}
                </p>
              )}
              <div className="mt-4 flex items-center justify-between">
                <span className="text-[11px] text-gray-500">
                  {new Date(biz.created_at * 1000).toLocaleDateString()}
                </span>
                {currentBusiness === biz.id ? (
                  <span className="rounded-full bg-sky-50 px-2.5 py-0.5 text-[11px] font-medium text-sky-700">
                    {t.businesses.current}
                  </span>
                ) : (
                  <button
                    onClick={() => setCurrentBusiness(biz.id)}
                    className="rounded-full border border-gray-300 px-2.5 py-0.5 text-[11px] text-gray-500 hover:border-sky-400 hover:text-sky-600 transition-colors"
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
