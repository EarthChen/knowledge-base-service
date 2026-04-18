import { ChevronRight, Home } from "lucide-react";
import { Link } from "react-router-dom";

function wikiPageLink(repository: string, pathTo: string): string {
  const encRepo = encodeURIComponent(repository);
  const segments = pathTo.split("/").filter(Boolean);
  const encPath = segments.map((s) => encodeURIComponent(s)).join("/");
  return encPath ? `/wiki/${encRepo}/${encPath}` : `/wiki/${encRepo}`;
}

type Props = {
  repository: string;
  path: string;
};

export default function WikiBreadcrumbs({ repository, path }: Props) {
  const segments = path.split("/").filter(Boolean);

  return (
    <nav
      aria-label="Breadcrumb"
      className="flex flex-wrap items-center gap-1 text-sm text-gray-600"
    >
      <Link
        to={`/wiki/${encodeURIComponent(repository)}`}
        className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium text-gray-700 hover:bg-gray-100 hover:text-gray-900"
      >
        <Home size={14} aria-hidden />
        {repository}
      </Link>
      {segments.map((seg, i) => {
        const to = wikiPageLink(
          repository,
          segments.slice(0, i + 1).join("/"),
        );
        const label = decodeURIComponent(seg);
        const last = i === segments.length - 1;
        return (
          <span key={to} className="inline-flex items-center gap-1">
            <ChevronRight size={14} className="text-gray-400" aria-hidden />
            {last ? (
              <span className="font-semibold text-gray-900">{label}</span>
            ) : (
              <Link
                to={to}
                className="rounded-md px-1.5 py-0.5 hover:bg-gray-100 hover:text-gray-900"
              >
                {label}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}
