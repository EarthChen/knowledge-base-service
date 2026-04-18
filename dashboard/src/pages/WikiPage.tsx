import { Link, useParams } from "react-router-dom";
import { BookOpen, ChevronRight } from "lucide-react";
import { useRepositories } from "../api/hooks";
import AskPanel from "../components/wiki/AskPanel";
import WikiContent from "../components/wiki/WikiContent";
import WikiSidebar from "../components/wiki/WikiSidebar";
import { useWikiPages } from "../hooks/useWikiPages";
import { useWikiPage } from "../hooks/useWikiPage";

function decodeWikiPathSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

export default function WikiPage() {
  const params = useParams();
  const repositoryRaw = params.repository;
  const repository = repositoryRaw
    ? decodeWikiPathSegment(repositoryRaw)
    : undefined;

  const splatRaw = (params["*"] as string | undefined) ?? "";
  const pagePath = splatRaw
    .split("/")
    .filter(Boolean)
    .map(decodeWikiPathSegment)
    .join("/");

  const reposQuery = useRepositories();
  const pagesQuery = useWikiPages(repository);
  const pageQuery = useWikiPage(repository, pagePath || undefined);

  if (!repository) {
    const repos = reposQuery.data?.repositories ?? [];
    return (
      <div className="mx-auto max-w-3xl space-y-6">
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-sky-50 text-sky-600">
              <BookOpen size={24} aria-hidden />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Wiki</h2>
              <p className="mt-1 text-sm text-gray-600">
                Browse generated wiki pages for an indexed repository. Choose a repository to
                continue.
              </p>
            </div>
          </div>
        </div>

        {reposQuery.isLoading && (
          <p className="text-sm text-gray-500">Loading repositories…</p>
        )}
        {reposQuery.isError && (
          <p className="text-sm text-red-600">
            {(reposQuery.error as Error).message}
          </p>
        )}
        {!reposQuery.isLoading && repos.length === 0 && (
          <p className="text-sm text-gray-600">
            No repositories found.{" "}
            <Link to="/repositories" className="text-sky-700 underline">
              Add or index a repository
            </Link>{" "}
            first.
          </p>
        )}
        {repos.length > 0 && (
          <ul className="grid gap-3 sm:grid-cols-2">
            {repos.map((r) => (
              <li key={r.repository}>
                <Link
                  to={`/wiki/${encodeURIComponent(r.repository)}`}
                  className="flex items-center justify-between rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm transition-colors hover:border-sky-200 hover:bg-sky-50/40"
                >
                  <span className="font-medium text-gray-900">{r.repository}</span>
                  <ChevronRight size={18} className="text-gray-400" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    );
  }

  const pages = pagesQuery.data?.pages ?? [];
  const contentError =
    pagePath && pageQuery.isError
      ? pageQuery.error instanceof Error
        ? pageQuery.error
        : new Error(String(pageQuery.error))
      : null;

  return (
    <div className="flex min-h-[min(70vh,860px)] flex-col gap-4 lg:flex-row lg:items-stretch">
      <WikiSidebar
        repository={repository}
        pages={pages}
        activePath={pagePath}
        pagesLoading={pagesQuery.isLoading}
        pagesError={
          pagesQuery.error instanceof Error
            ? pagesQuery.error
            : pagesQuery.error
              ? new Error(String(pagesQuery.error))
              : null
        }
      />

      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <WikiContent
          repository={repository}
          pagePath={pagePath}
          detail={pageQuery.data}
          isLoading={Boolean(pagePath) && pageQuery.isLoading}
          error={contentError}
        />

        <AskPanel repository={repository} />
      </div>
    </div>
  );
}
