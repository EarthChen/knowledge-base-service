from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MethodSnippet:
    module_name: str
    method_name: str
    score: float
    module_docstring: str
    file_path: str

    def format_for_prompt(self) -> str:
        lines = [
            f"Module: {self.module_name}",
            f"Method: {self.method_name}",
        ]
        doc = (self.module_docstring or "").strip()
        if doc:
            lines.append(f"Doc: {doc}")
        if (self.file_path or "").strip():
            lines.append(f"Path: {self.file_path.strip()}")
        return "\n".join(lines)


def _estimate_tokens(text: str) -> float:
    return len(text) / 4.0


def _count_in_degree(modules: list[dict]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for mod in modules:
        props = mod.get("properties") or {}
        for call in props.get("calls") or []:
            if not isinstance(call, str) or "." not in call:
                continue
            mod_name, _, meth_name = call.rpartition(".")
            if not mod_name or not meth_name:
                continue
            key = (mod_name, meth_name)
            counts[key] = counts.get(key, 0) + 1
    return counts


def _score_method(
    module_uid: str,
    module_name: str,
    method_name: str,
    module_docstring: str,
    entity_roles: dict[str, str],
    in_degree: dict[tuple[str, str], int],
) -> float:
    score = 0.0
    role = entity_roles.get(module_uid, "")
    if role == "entry_point":
        score += 10.0
    score += in_degree.get((module_name, method_name), 0) * 3.0
    if (module_docstring or "").strip():
        score += 2.0
    if not method_name.startswith("_"):
        score += 1.0
    return score


def select_key_snippets(
    modules: list[dict],
    entity_roles: dict[str, str],
    budget_tokens: int = 2000,
    max_per_module: int = 3,
) -> list[MethodSnippet]:
    if not modules:
        return []

    in_degree = _count_in_degree(modules)

    per_module_snippets: list[MethodSnippet] = []
    for mod in modules:
        props = mod.get("properties") or {}
        module_name = props.get("name") or ""
        module_uid = mod.get("uid") or ""
        methods = props.get("methods") or []
        docstring = props.get("docstring") or ""
        file_path = props.get("path") or ""

        candidates: list[MethodSnippet] = []
        for method_name in methods:
            if not isinstance(method_name, str):
                continue
            sc = _score_method(
                module_uid,
                module_name,
                method_name,
                str(docstring),
                entity_roles,
                in_degree,
            )
            candidates.append(
                MethodSnippet(
                    module_name=module_name,
                    method_name=method_name,
                    score=sc,
                    module_docstring=str(docstring),
                    file_path=str(file_path),
                )
            )

        candidates.sort(key=lambda s: (-s.score, s.method_name, s.module_name))
        per_module_snippets.extend(candidates[: max(0, max_per_module)])

    per_module_snippets.sort(
        key=lambda s: (-s.score, s.module_name, s.method_name)
    )

    result: list[MethodSnippet] = []
    used_tokens = 0.0
    for snippet in per_module_snippets:
        chunk = snippet.format_for_prompt()
        t = _estimate_tokens(chunk)
        if used_tokens + t > budget_tokens:
            break
        result.append(snippet)
        used_tokens += t

    return result
