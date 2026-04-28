"""In-memory cache for WikiLink title→URL resolution during wiki generation."""

from __future__ import annotations

from urllib.parse import quote


class WikiLinkCache:
    """Pre-loads and maintains wiki page title→URL mappings to avoid repeated DB queries."""

    def __init__(self) -> None:
        self._title_to_url: dict[str, str] = {}
        self._path_to_title: dict[str, str] = {}
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    async def warm_up(self, wiki_store: object, repository: str) -> int:
        """Load all existing wiki page titles from store. Returns count loaded."""
        result = await wiki_store.list_wiki_pages_all(repository)  # type: ignore[attr-defined]
        rows = getattr(result, "data", None) or []
        count = 0
        for row in rows:
            title = row.get("title")
            path = row.get("path")
            if title and path:
                self.register(str(title), str(path))
                count += 1
        self._loaded = True
        return count

    def register(self, title: str, path: str) -> None:
        """Register a page into the cache (called after each page is composed)."""
        t = title.strip()
        if not t:
            return
        url = f"/wiki?path={quote(path, safe='')}"
        self._title_to_url[t] = url
        self._path_to_title[path] = t

    def get_index(self) -> dict[str, str]:
        """Return title→URL mapping for wikilink resolution."""
        return dict(self._title_to_url)

    def get_title_for_path(self, path: str) -> str | None:
        """Reverse lookup: path→title (for backlink generation)."""
        return self._path_to_title.get(path)
