export function SkeletonCard() {
  return (
    <div className="animate-pulse rounded-xl border border-gray-200 bg-white p-5">
      <div className="h-3 w-20 rounded bg-gray-200" />
      <div className="mt-3 h-7 w-16 rounded bg-gray-200" />
    </div>
  );
}

export function SkeletonLine({ className = "" }: { className?: string }) {
  return (
    <div className={`animate-pulse rounded bg-gray-200 ${className}`} />
  );
}
