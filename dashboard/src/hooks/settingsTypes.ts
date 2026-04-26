export type SettingSource = "db" | "env" | "default";

export type SettingItem = {
  value: string;
  source: SettingSource;
  sensitive: boolean;
};

export type SettingsCategory = Record<string, SettingItem>;

export type SettingsResponse = {
  categories: Record<string, SettingsCategory>;
};

export type CategoryResponse = {
  category: string;
  settings: SettingsCategory;
};

export type SettingUpdate = {
  key: string;
  value: string;
  category: string;
};

export type SettingsBatchUpdate = {
  settings: SettingUpdate[];
};

export type TestConnectionResponse = {
  status: "ok" | "error";
  target: string;
  message: string;
};
