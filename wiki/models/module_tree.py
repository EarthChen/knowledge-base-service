"""Data model for hierarchical module decomposition tree."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModuleNode:
    canonical_key: str
    entity_uids: list[str]
    file_paths: list[str]
    title: str = ""
    description: str = ""
    children: list[ModuleNode] = field(default_factory=list)
    token_estimate: int = 0
    page: Any = None

    def is_leaf(self) -> bool:
        return len(self.children) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_key": self.canonical_key,
            "entity_uids": self.entity_uids,
            "file_paths": self.file_paths,
            "title": self.title,
            "description": self.description,
            "token_estimate": self.token_estimate,
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModuleNode:
        children = [cls.from_dict(c) for c in data.get("children", [])]
        return cls(
            canonical_key=data["canonical_key"],
            entity_uids=data.get("entity_uids", []),
            file_paths=data.get("file_paths", []),
            title=data.get("title", ""),
            description=data.get("description", ""),
            token_estimate=data.get("token_estimate", 0),
            children=children,
        )


@dataclass
class ModuleTree:
    roots: list[ModuleNode]
    repo_id: str

    def topological_order(self) -> list[ModuleNode]:
        """Bottom-up order: leaves first, roots last."""
        result: list[ModuleNode] = []
        visited: set[str] = set()

        def _dfs(node: ModuleNode) -> None:
            if node.canonical_key in visited:
                return
            visited.add(node.canonical_key)
            for child in node.children:
                _dfs(child)
            result.append(node)

        for root in self.roots:
            _dfs(root)
        return result

    def all_nodes(self) -> list[ModuleNode]:
        result: list[ModuleNode] = []
        stack = list(self.roots)
        while stack:
            node = stack.pop()
            result.append(node)
            stack.extend(node.children)
        return result

    def to_dicts(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.roots]

    @classmethod
    def from_dicts(cls, data: list[dict[str, Any]], repo_id: str) -> ModuleTree:
        roots = [ModuleNode.from_dict(d) for d in data]
        return cls(roots=roots, repo_id=repo_id)
