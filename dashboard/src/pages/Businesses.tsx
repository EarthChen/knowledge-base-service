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
  const { addToast } = useToast();
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
      addToast(t.businesses.created, "success");
      setFormId("");
      setFormName("");
      setFormDesc("");
      setShowForm(false);
    } catch (err: unknown) {
      addToast(String((err as Error).message || t.businesses.createFailed), "error");
    }
  };

  const handleDelete = async (id: string) => {
    const yes = window.confirm(t.businesses.deleteConfirm.replace("{id}", id));
    if (!yes) return;
    try {
      await deleteMut.mutateAsync(id);
      addToast(t.businesses.deleted.replace("{id}", id), "success");
      if (currentBusiness === id) {
        setCurrentBusiness("default");
      }
    } catch (err: unknown) {
      addToast(String((err as Error).message || t.businesses.deleteFailed), "error");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">{t.businesses.title}</h2>
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
        <div className="rounded-xl border border-slate-700 bg-slate-800/50 p-5 space-y-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">
              {t.businesses.idLabel}
            </label>
            <input
              value={formId}
              onChange={(e) => setFormId(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""))}
              placeholder="team-alpha"
              className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white placeholder-slate-500 focus:border-sky-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">
              {t.businesses.nameLabel}
            </label>
            <input
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              placeholder="Team Alpha"
              className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white placeholder-slate-500 focus:border-sky-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-400">
              {t.businesses.descLabel}
            </label>
            <input
              value={formDesc}
              onChange={(e) => setFormDesc(e.target.value)}
              placeholder={t.businesses.descPlaceholder}
              className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white placeholder-slate-500 focus:border-sky-500 focus:outline-none"
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
              className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-400 hover:bg-slate-800 transition-colors"
            >
              {t.businesses.cancel}
            </button>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="text-sm text-slate-500">Loading...</div>
      ) : !data?.businesses?.length ? (
        <div className="rounded-xl border border-slate-800 p-8 text-center text-sm text-slate-500">
          {t.businesses.empty}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {data.businesses.map((biz) => (
            <div
              key={biz.id}
              className={`group relative rounded-xl border p-5 transition-colors ${
                currentBusiness === biz.id
                  ? "border-sky-500/50 bg-sky-500/5"
                  : "border-slate-800 bg-slate-800/30 hover:border-slate-700"
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div
                    className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                      currentBusiness === biz.id
                        ? "bg-sky-500/15 text-sky-400"
                        : "bg-slate-800 text-slate-400"
                    }`}
                  >
                    <Building2 size={20} />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-white">{biz.name}</h3>
                    <p className="text-xs text-slate-500">{biz.id}</p>
                  </div>
                </div>
                {isAdmin && biz.id !== "default" && (
                  <button
                    onClick={() => handleDelete(biz.id)}
                    className="rounded p-1 text-slate-600 opacity-0 hover:bg-red-500/10 hover:text-red-400 group-hover:opacity-100 transition-all"
                    title={t.businesses.deleteBtn}
                  >
                    <Trash2 size={16} />
                  </button>
                )}
              </div>
              {biz.description && (
                <p className="mt-3 text-xs text-slate-400 line-clamp-2">
                  {biz.description}
                </p>
              )}
              <div className="mt-4 flex items-center justify-between">
                <span className="text-[11px] text-slate-600">
                  {new Date(biz.created_at * 1000).toLocaleDateString()}
                </span>
                {currentBusiness === biz.id ? (
                  <span className="rounded-full bg-sky-500/15 px-2.5 py-0.5 text-[11px] font-medium text-sky-400">
                    {t.businesses.current}
                  </span>
                ) : (
                  <button
                    onClick={() => setCurrentBusiness(biz.id)}
                    className="rounded-full border border-slate-700 px-2.5 py-0.5 text-[11px] text-slate-400 hover:border-sky-500 hover:text-sky-400 transition-colors"
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
