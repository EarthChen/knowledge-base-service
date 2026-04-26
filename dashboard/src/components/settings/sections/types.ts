import type { Translations } from "../../../i18n/types";

export type SectionProps = {
  values: Record<string, string>;
  meta: Record<string, { source: string; sensitive: boolean }>;
  onChange: (key: string, value: string) => void;
  t: Translations;
};

export type ConnectionSectionProps = SectionProps & {
  onTestConnection: (target: string) => void;
  testConnectionPending: boolean;
};
