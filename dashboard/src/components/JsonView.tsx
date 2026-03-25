export default function JsonView({ data }: { data: unknown }) {
  const formatted = JSON.stringify(data, null, 2);
  return (
    <pre className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-950/80 p-4 font-mono text-xs leading-relaxed text-slate-300">
      {formatted}
    </pre>
  );
}
