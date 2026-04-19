export default function SearchResultSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="animate-pulse rounded-xl border border-gray-200 bg-white p-4"
        >
          <div className="flex items-center gap-3">
            <div className="h-5 w-16 rounded bg-gray-200" />
            <div className="h-4 w-40 rounded bg-gray-200" />
            <div className="ml-auto h-4 w-20 rounded bg-gray-100" />
          </div>
          <div className="mt-3 space-y-2">
            <div className="h-3 w-full rounded bg-gray-100" />
            <div className="h-3 w-3/4 rounded bg-gray-100" />
          </div>
          <div className="mt-3 flex gap-2">
            <div className="h-3 w-32 rounded bg-gray-100" />
            <div className="h-3 w-16 rounded bg-gray-100" />
          </div>
        </div>
      ))}
    </div>
  );
}
