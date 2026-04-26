import { Box } from "lucide-react";
import { configFieldLabel, configOptionLabel, humanizeKey, sourceBadge } from "../configFieldLabels";
import SettingsCard from "../SettingsCard";
import SettingsInput from "../SettingsInput";
import SettingsSelect from "../SettingsSelect";
import SettingsToggle from "../SettingsToggle";
import type { SectionProps } from "./types";

export default function EmbeddingSection({ values, meta, onChange, t }: SectionProps) {
  const boolVal = (key: string) => values[key] === "true";

  const deviceOpts = [
    { value: "auto", label: configOptionLabel("auto", t) },
    { value: "cpu", label: humanizeKey("cpu") },
    { value: "cuda", label: humanizeKey("cuda") },
    { value: "mps", label: humanizeKey("mps") },
  ];
  const backendOpts = [
    { value: "onnx", label: humanizeKey("onnx") },
    { value: "torch", label: humanizeKey("torch") },
    { value: "auto", label: configOptionLabel("auto", t) },
  ];

  return (
    <SettingsCard title={t.configSettings.embeddingTitle} icon={<Box size={18} className="text-sky-600" />}>
      <SettingsInput
        label={configFieldLabel("embedding.model_name", t)}
        value={values["embedding.model_name"] ?? ""}
        onChange={(v) => onChange("embedding.model_name", v)}
        source={sourceBadge("embedding.model_name", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("embedding.dimension", t)}
        type="number"
        value={values["embedding.dimension"] ?? ""}
        onChange={(v) => onChange("embedding.dimension", v)}
        source={sourceBadge("embedding.dimension", meta, t)}
      />
      <SettingsSelect
        label={configFieldLabel("embedding.device", t)}
        value={values["embedding.device"] || "auto"}
        onChange={(v) => onChange("embedding.device", v)}
        source={sourceBadge("embedding.device", meta, t)}
        options={deviceOpts}
      />
      <SettingsSelect
        label={configFieldLabel("embedding.backend", t)}
        value={values["embedding.backend"] || "onnx"}
        onChange={(v) => onChange("embedding.backend", v)}
        source={sourceBadge("embedding.backend", meta, t)}
        options={backendOpts}
      />
      <SettingsInput
        label={configFieldLabel("embedding.batch_size", t)}
        type="number"
        value={values["embedding.batch_size"] ?? ""}
        onChange={(v) => onChange("embedding.batch_size", v)}
        source={sourceBadge("embedding.batch_size", meta, t)}
      />
      <SettingsToggle
        label={configFieldLabel("embedding.use_fp16", t)}
        checked={boolVal("embedding.use_fp16")}
        onChange={(v) => onChange("embedding.use_fp16", v ? "true" : "false")}
        source={sourceBadge("embedding.use_fp16", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("embedding.max_length", t)}
        type="number"
        value={values["embedding.max_length"] ?? ""}
        onChange={(v) => onChange("embedding.max_length", v)}
        source={sourceBadge("embedding.max_length", meta, t)}
      />
    </SettingsCard>
  );
}
