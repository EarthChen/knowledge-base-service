import { useI18n } from "../../i18n/context";

interface Props {
  value: string | null;
  onChange: (tier: string | null) => void;
}

export function WikiTierSelector({ value, onChange }: Props) {
  const { t } = useI18n();
  const tiers = [
    { value: "", label: t.wiki.tier_selector.comprehensive },
    { value: "standard", label: t.wiki.tier_selector.standard },
    { value: "essential", label: t.wiki.tier_selector.essential },
  ];
  return (
    <select
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      className="rounded border bg-transparent px-1.5 py-1 text-xs"
      aria-label={t.wiki.tier_selector.aria_label}
    >
      {tiers.map((tier) => (
        <option key={tier.value} value={tier.value}>
          {tier.label}
        </option>
      ))}
    </select>
  );
}
