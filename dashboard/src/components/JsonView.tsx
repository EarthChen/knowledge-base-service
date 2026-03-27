export default function JsonView({ data }: { data: unknown }) {
  const formatted = JSON.stringify(data, null, 2);
  return (
    <pre className="overflow-x-auto rounded-lg border border-gray-200 bg-gray-50 p-4 font-mono text-xs leading-relaxed text-gray-700">
      {formatted}
    </pre>
  );
}
