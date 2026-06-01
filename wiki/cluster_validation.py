"""Post-cluster topology validation for directory scatter detection (G8)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_GENERIC_DIRS = frozenset(
    {"src", "main", "java", "kotlin", "com", "org", "net", "io", "impl", "internal", "lib", "pkg", "app"}
)


def _extract_top_business_dir(path: str) -> str:
    """Extract first non-generic directory segment from a module path."""
    if not path:
        return "root"
    parts = Path(path.replace("\\", "/")).parts
    for part in parts:
        if part.lower() not in _GENERIC_DIRS and not part.startswith("."):
            return part.lower()
    return parts[-2].lower() if len(parts) > 1 else "root"


def _lookup_module_path(module_paths: dict[str, str], repo: str, name: str) -> str:
    compound = f"{repo}|{name}"
    return module_paths.get(compound, module_paths.get(name, ""))


@dataclass
class ClusterScatterReport:
    domain_slug: str
    module_count: int
    unique_top_dirs: int
    scatter_ratio: float
    top_dirs: list[str]
    is_scattered: bool


def validate_cluster_topology(
    communities: list[set[tuple[str, str]]],
    module_paths: dict[str, str],
    *,
    scatter_threshold: float = 0.6,
    min_modules_for_check: int = 4,
) -> list[ClusterScatterReport]:
    """Validate that clusters have topological coherence (directory locality).

    Returns list of reports for scattered clusters only.
    """
    scattered: list[ClusterScatterReport] = []

    for idx, community in enumerate(communities):
        if not community:
            continue

        top_dirs: list[str] = []
        for repo, name in community:
            path = _lookup_module_path(module_paths, repo, name)
            top_dirs.append(_extract_top_business_dir(path))

        module_count = len(top_dirs)
        unique_dirs = sorted(set(top_dirs))
        unique_count = len(unique_dirs)
        scatter_ratio = unique_count / module_count if module_count else 0.0
        is_scattered = module_count >= min_modules_for_check and scatter_ratio > scatter_threshold

        if is_scattered:
            scattered.append(
                ClusterScatterReport(
                    domain_slug=f"cluster-{idx}",
                    module_count=module_count,
                    unique_top_dirs=unique_count,
                    scatter_ratio=scatter_ratio,
                    top_dirs=unique_dirs,
                    is_scattered=True,
                )
            )

    return scattered
