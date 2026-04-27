interface Props {
  value: string | null;
  onChange: (tier: string | null) => void;
}

const TIERS = [
  { value: "", label: "Comprehensive" },
  { value: "standard", label: "Standard" },
  { value: "essential", label: "Essential" },
] as const;

export function WikiTierSelector({ value, onChange }: Props) {
  return (
    <select
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      className="rounded border bg-transparent px-1.5 py-1 text-xs"
      aria-label="Wiki tier filter"
      role="combobox"
    >
      {TIERS.map((t) => (
        <option key={t.value} value={t.value}>
          {t.label}
        </option>
      ))}
    </select>
  );
}
