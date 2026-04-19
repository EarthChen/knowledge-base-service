"""Wiki lint / health checks: graph vs wiki consistency."""

from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, runtime_checkable

from store.wiki_store import WikiStore
from wiki.cache import WikiCache
from wiki.models import WikiPage, parse_scope


@dataclass
class LintIssue:
    severity: Literal["error", "warning", "info"]
    category: str  # staleness | orphan | broken_link | coverage_gap | outdated
    message: str
    page_path: str | None = None
    entity_name: str | None = None
    suggestion: str | None = None


@dataclass
class LintReport:
    issues: list[LintIssue]
    stats: dict[str, int]
    checked_at: str
    scope: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "issues": [asdict(i) for i in self.issues],
            "stats": dict(self.stats),
            "checked_at": self.checked_at,
            "scope": self.scope,
        }


_ROOT_PAGE_NAMES = frozenset(
    {
        "index.md",
        "overview.md",
        "readme.md",
        "readme",
        "index",
        "overview",
    },
)


_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")


@runtime_checkable
class _GraphExecutePort(Protocol):
    async def execute_query(self, cypher: str, params: dict[str, Any] | None = None) -> Any: ...


def _is_root_wiki_path(path: str) -> bool:
    p = path.strip().lower()
    base = p.rsplit("/", 1)[-1]
    return base in _ROOT_PAGE_NAMES


def _normalize_link_target(href: str) -> str | None:
    h = href.strip()
    if not h or h.startswith(("#", "http://", "https://", "mailto:", "source://", "vscode://", "cursor://", "idea://")):
        return None
    if ".md" not in h.lower():
        return None
    return h.split("#", 1)[0].strip()


class WikiLintService:
    """Runs staleness, orphan, broken-link, coverage, and outdated checks."""

    def __init__(
        self,
        store: _GraphExecutePort,
        wiki_cache: WikiCache | None = None,
        repo_registry: Any | None = None,
        wiki_store: WikiStore | None = None,
    ) -> None:
        self._store = store
        self._wiki_store = wiki_store or WikiStore(store)
        self._cache = wiki_cache
        self._repo_registry = repo_registry

    async def lint(self, repository: str, *, scope: str = "all") -> LintReport:
        checks = await asyncio.gather(
            self._check_staleness(repository),
            self._check_orphans(repository),
            self._check_broken_links(repository),
            self._check_coverage_gaps(repository),
            self._check_outdated_content(repository),
        )
        issues = [issue for group in checks for issue in group]
        issues = self._filter_by_scope(issues, scope)
        stats = {"total": len(issues), "errors": 0, "warnings": 0, "info": 0}
        for issue in issues:
            if issue.severity == "error":
                stats["errors"] += 1
            elif issue.severity == "warning":
                stats["warnings"] += 1
            else:
                stats["info"] += 1
        return LintReport(
            issues=issues,
            stats=stats,
            checked_at=datetime.now(timezone.utc).isoformat(),
            scope=scope,
        )

    def _filter_by_scope(self, issues: list[LintIssue], scope: str) -> list[LintIssue]:
        raw = (scope or "all").strip()
        if not raw or raw == "all":
            return issues
        try:
            sp = parse_scope(raw)
        except ValueError:
            return issues
        if sp.scope_type == "repo":
            return issues

        def keep(issue: LintIssue) -> bool:
            pp = issue.page_path or ""
            if sp.scope_type == "module" and sp.value:
                prefix = sp.value.strip().rstrip("/")
                return pp == prefix or pp.startswith(prefix + "/")
            if sp.scope_type == "class" and sp.value:
                fqn = sp.value.strip()
                simple = fqn.split("#")[0].rsplit(".", 1)[-1]
                if issue.entity_name and issue.entity_name == simple:
                    return True
                return (
                    pp.endswith(f"/{simple}.md")
                    or pp == f"{simple}.md"
                    or pp.endswith(f"classes/{simple}.md")
                )
            return True

        return [i for i in issues if keep(i)]

    async def _wiki_pages_for_repo(self, repository: str) -> list[dict[str, Any]]:
        rows = await self._wiki_store.list_wiki_pages_for_repo(repository)
        data = getattr(rows, "data", None) or []
        pages = [dict(r) for r in data]
        if pages or self._cache is None:
            return pages
        return self._pages_from_cache(repository)

    def _pages_from_cache(self, repository: str) -> list[dict[str, Any]]:
        assert self._cache is not None
        return [self._wiki_page_to_row(p) for p in self._cache.list_pages_for_repository(repository)]

    @staticmethod
    def _wiki_page_to_row(p: WikiPage) -> dict[str, Any]:
        ga = p.metadata.generated_at
        return {
            "path": p.path,
            "title": p.title,
            "content": p.content,
            "generated_at": ga or "",
            "referenced_entity_uids": [],
        }

    async def _check_staleness(self, repository: str) -> list[LintIssue]:
        issues: list[LintIssue] = []
        graph_rows = await self._wiki_store.lint_stale_entity_refs(repository)
        for r in getattr(graph_rows, "data", None) or []:
            uid = str(r.get("stale_uid", "") or "")
            pp = str(r.get("page_path", "") or "")
            if not uid:
                continue
            issues.append(
                LintIssue(
                    severity="error",
                    category="staleness",
                    message=f"Wiki references entity uid '{uid}' that is not in the graph",
                    page_path=pp or None,
                    entity_name=uid,
                    suggestion="Re-generate wiki or remove stale references.",
                ),
            )

        cache_only_pages: list[WikiPage] = []
        graph_pages = await self._wiki_store.count_wiki_pages_for_repository(repository)
        cnt = 0
        if getattr(graph_pages, "data", None):
            cnt = int(graph_pages.data[0].get("cnt") or 0)
        if cnt == 0 and self._cache is not None:
            cache_only_pages = self._cache.list_pages_for_repository(repository)

        for page in cache_only_pages:
            for loc in page.source_locations:
                fqn = (loc.fqn or "").strip()
                if not fqn:
                    continue
                chk = await self._wiki_store.entity_uid_by_fqn(repository, fqn)
                rows = getattr(chk, "data", None) or []
                if rows:
                    continue
                issues.append(
                    LintIssue(
                        severity="error",
                        category="staleness",
                        message=f"Source location FQN '{fqn}' not found in graph",
                        page_path=page.path,
                        entity_name=fqn,
                        suggestion="Re-index repository or update wiki source_locations.",
                    ),
                )
        return issues

    async def _check_orphans(self, repository: str) -> list[LintIssue]:
        res = await self._wiki_store.wiki_orphan_in_degrees(repository)
        issues: list[LintIssue] = []
        rows = getattr(res, "data", None) or []
        if not rows and self._cache is not None:
            pages = self._cache.list_pages_for_repository(repository)
            known = {p.path for p in pages}
            for p in pages:
                if _is_root_wiki_path(p.path):
                    continue
                linked = False
                for other in pages:
                    if other.path == p.path:
                        continue
                    if p.title and f"[[{p.title}]]" in other.content:
                        linked = True
                        break
                    if f"]({p.path})" in other.content:
                        linked = True
                        break
                    for m in _MD_LINK_RE.finditer(other.content):
                        tgt = _normalize_link_target(m.group(2))
                        if tgt and (tgt == p.path or p.path.endswith("/" + tgt) or p.path.endswith(tgt)):
                            linked = True
                            break
                    if linked:
                        break
                if not linked and p.path in known:
                    issues.append(
                        LintIssue(
                            severity="warning",
                            category="orphan",
                            message="Wiki page has no incoming wikilinks from other wiki pages",
                            page_path=p.path,
                            suggestion="Link this page from overview or related pages.",
                        ),
                    )
            return issues

        for r in rows:
            path = str(r.get("path", "") or "")
            deg = int(r.get("in_degree", 0) or 0)
            if deg > 0:
                continue
            if _is_root_wiki_path(path):
                continue
            issues.append(
                LintIssue(
                    severity="warning",
                    category="orphan",
                    message="Wiki page has no incoming WIKILINK edges in the graph",
                    page_path=path,
                    suggestion="Add WIKILINK relationships from hub pages.",
                ),
            )
        return issues

    async def _check_broken_links(self, repository: str) -> list[LintIssue]:
        pages = await self._wiki_pages_for_repo(repository)
        titles = {str(p.get("title", "")) for p in pages if p.get("title")}
        paths = {str(p.get("path", "")) for p in pages if p.get("path")}
        issues: list[LintIssue] = []
        for p in pages:
            content = str(p.get("content", "") or "")
            page_path = str(p.get("path", "") or "")
            for m in _MD_LINK_RE.finditer(content):
                tgt = _normalize_link_target(m.group(2))
                if not tgt:
                    continue
                if tgt not in paths and not any(p.endswith("/" + tgt) or p == tgt for p in paths):
                    issues.append(
                        LintIssue(
                            severity="error",
                            category="broken_link",
                            message=f"Markdown link target '{tgt}' not found",
                            page_path=page_path,
                            suggestion="Fix path or generate missing page.",
                        ),
                    )
            for m in _WIKILINK_RE.finditer(content):
                title = m.group(1).strip()
                if title and title not in titles:
                    issues.append(
                        LintIssue(
                            severity="error",
                            category="broken_link",
                            message=f"Wikilink '[['{title}']]' does not match any wiki page title",
                            page_path=page_path,
                            entity_name=title,
                        ),
                    )
        return issues

    async def _check_coverage_gaps(self, repository: str) -> list[LintIssue]:
        res = await self._wiki_store.lint_coverage_gaps(repository)
        issues: list[LintIssue] = []
        for r in getattr(res, "data", None) or []:
            name = str(r.get("name", "") or "")
            if not name:
                continue
            issues.append(
                LintIssue(
                    severity="warning",
                    category="coverage_gap",
                    message=f"Class '{name}' has service/controller/repository role but no wiki page",
                    entity_name=name,
                    suggestion="Generate a class-level wiki page.",
                ),
            )
        return issues

    def _last_indexed_iso(self, repository: str) -> str | None:
        if self._repo_registry is None:
            return None
        try:
            entries = self._repo_registry.list_all()
        except Exception:
            return None
        for entry in entries:
            if str(entry.get("repository", "")) == repository:
                v = entry.get("last_indexed")
                return str(v) if v else None
        return None

    async def _check_outdated_content(self, repository: str) -> list[LintIssue]:
        issues: list[LintIssue] = []
        last_idx = self._last_indexed_iso(repository)
        if not last_idx:
            return issues
        try:
            idx_dt = datetime.fromisoformat(last_idx.replace("Z", "+00:00"))
        except ValueError:
            return issues

        pages = await self._wiki_pages_for_repo(repository)
        for p in pages:
            raw = str(p.get("generated_at", "") or "").strip()
            if not raw:
                continue
            try:
                gen_dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if gen_dt < idx_dt:
                issues.append(
                    LintIssue(
                        severity="info",
                        category="outdated",
                        message="Wiki page generated_at is older than last repository index time",
                        page_path=str(p.get("path", "") or None) or None,
                        suggestion="Re-generate wiki after indexing.",
                    ),
                )
        return issues
