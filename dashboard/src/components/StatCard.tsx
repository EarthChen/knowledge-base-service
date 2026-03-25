import type { LucideIcon } from "lucide-react";

interface StatCardProps {
  label: string;
  value: number | string;
  icon: LucideIcon;
  color: string;
}

export default function StatCard({ label, value, icon: Icon, color }: StatCardProps) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-850 p-5">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
            {label}
          </p>
          <p className="mt-2 text-2xl font-bold text-white">{value ?? "—"}</p>
        </div>
        <div className={`rounded-lg p-2.5 ${color}`}>
          <Icon size={22} />
        </div>
      </div>
    </div>
  );
}
