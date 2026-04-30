"""Wiki-specific exception types shared across wiki submodules."""


class WikiRepoNotFoundError(Exception):
    """Raised when a repository has not been indexed."""

    def __init__(self, repository: str) -> None:
        self.repository = repository
        super().__init__(f"Repository {repository!r} is not indexed")
