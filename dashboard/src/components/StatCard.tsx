import type { LucideIcon } from "lucide-react";

interface StatCardProps {
  label: string;
  value: number | string;
  icon: LucideIcon;
  color: string;
}

export default function StatCard({ label, value, icon: Icon, color }: StatCardProps) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-gray-500">
            {label}
          </p>
          <p className="mt-2 text-2xl font-bold text-gray-900">{value ?? "—"}</p>
        </div>
        <div className={`rounded-lg p-2.5 ${color}`}>
          <Icon size={22} />
        </div>
      </div>
    </div>
  );
}
