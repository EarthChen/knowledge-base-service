"""Resolve import strings to indexed relative file paths (pure logic, no I/O)."""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

_JS_TS_EXTS_TRY_ORDER = (
    ".tsx",
    ".jsx",
    ".ts",
    ".js",
    ".mjs",
    ".cjs",
)
_JS_INDEX_NAMES = frozenset({"index.ts", "index.tsx", "index.js", "index.jsx", "index.mjs", "index.cjs"})


def _normalize_rel(p: str) -> str:
    return p.replace("\\", "/")


class ImportResolver:
    """Resolves import statements to actual file paths within indexed repositories."""

    def __init__(self, file_index: dict[str, str]) -> None:
        """file_index: mapping from relative file path → module-style name (dot notation)."""
        self._file_index = file_index
        self._reverse_index: dict[str, list[str]] = {}
        self._build_reverse_index()

    def _build_reverse_index(self) -> None:
        for path, mod in self._file_index.items():
            self._reverse_index.setdefault(mod, []).append(path)

    @staticmethod
    def build_file_index(file_paths: list[str]) -> dict[str, str]:
        """Convert file paths to module-style names for lookup."""
        out: dict[str, str] = {}
        for raw in file_paths:
            fp = _normalize_rel(raw)
            lower = fp.lower()
            if lower.endswith(".py"):
                stem = Path(fp).stem
                dir_parts = [x for x in Path(fp).parent.parts if x not in (".",)]
                if stem == "__init__":
                    out[raw] = ".".join(dir_parts) if dir_parts else "__init__"
                else:
                    out[raw] = ".".join([*dir_parts, stem])
            elif lower.endswith(".java"):
                stem = Path(fp).stem
                dir_parts = [x for x in Path(fp).parent.parts if x not in (".",)]
                out[raw] = ".".join([*dir_parts, stem])
            elif lower.endswith(".go"):
                stem = Path(fp).stem
                dir_parts = [x for x in Path(fp).parent.parts if x not in (".",)]
                out[raw] = ".".join([*dir_parts, stem])
            elif any(
                lower.endswith(ext)
                for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
            ):
                p = Path(fp)
                stem = p.stem.lower()
                parent_parts = [x for x in p.parent.parts if x not in (".",)]
                if stem == "index":
                    out[raw] = ".".join(parent_parts) if parent_parts else stem
                else:
                    out[raw] = ".".join([*parent_parts, p.stem])
            else:
                stem = Path(fp).stem
                dir_parts = [x for x in Path(fp).parent.parts if x not in (".",)]
                out[raw] = ".".join([*dir_parts, stem])
        return out

    @staticmethod
    def build_module_index(file_paths: list[str]) -> dict[str, list[str]]:
        """Build module name → list of file paths (reverse lookup)."""
        fi = ImportResolver.build_file_index(file_paths)
        rev: dict[str, list[str]] = {}
        for path, mod in fi.items():
            rev.setdefault(mod, []).append(path)
        return rev

    def resolve(self, import_path: str, source_file: str, language: str) -> str | None:
        """Resolve an import path to the best-matching file path."""
        lang = language.lower()
        if lang == "python":
            return self._resolve_python(import_path.strip(), _normalize_rel(source_file))
        if lang in ("javascript", "typescript", "tsx", "jsx"):
            return self._resolve_js_ts(import_path.strip(), _normalize_rel(source_file))
        if lang == "java":
            return self._resolve_java(import_path.strip())
        if lang == "go":
            return self._resolve_go(import_path.strip())
        return None

    def _pick(self, module_key: str) -> str | None:
        paths = self._reverse_index.get(module_key)
        if not paths:
            return None
        return sorted(paths)[0]

    def _resolve_python(self, import_path: str, source_file: str) -> str | None:
        if not import_path:
            return None
        if import_path.startswith("."):
            return self._resolve_python_relative(import_path, source_file)

        parts = import_path.split(".")
        base = "/".join(parts)

        cand = f"{base}.py"
        if cand in self._file_index:
            return cand

        mod_key = ".".join(parts)
        hit = self._pick(mod_key)
        if hit:
            return hit

        init_path = f"{base}/__init__.py"
        if init_path in self._file_index:
            return init_path

        return self._pick(import_path)

    def _resolve_python_relative(self, import_path: str, source_file: str) -> str | None:
        src = Path(source_file)
        dir_parts = list(src.parent.parts)

        m = re.match(r"^(\.+)(.*)$", import_path)
        if not m:
            return None
        dots, rest = m.group(1), m.group(2).strip(".")
        level = len(dots) - 1
        if level > len(dir_parts):
            return None
        base_dir_parts = dir_parts[: len(dir_parts) - level] if level else dir_parts

        if rest:
            sub_parts = [p for p in rest.split(".") if p]
            path_parts = base_dir_parts + sub_parts
        else:
            path_parts = base_dir_parts

        if not path_parts:
            return None

        base = "/".join(path_parts)
        cand = f"{base}.py"
        if cand in self._file_index:
            return cand

        mod_key = ".".join(path_parts)
        hit = self._pick(mod_key)
        if hit:
            return hit

        init_path = f"{base}/__init__.py"
        if init_path in self._file_index:
            return init_path

        return self._pick(mod_key)

    def _resolve_js_ts(self, import_path: str, source_file: str) -> str | None:
        if not import_path.startswith((".", "/")):
            return None
        src = _normalize_rel(source_file)
        src_dir = posixpath.dirname(src)
        joined = posixpath.normpath(posixpath.join(src_dir, import_path.replace("\\", "/")))
        rel = joined.lstrip("/")
        if rel.startswith("../"):
            parts: list[str] = []
            for seg in rel.split("/"):
                if seg == "..":
                    if parts:
                        parts.pop()
                elif seg and seg != ".":
                    parts.append(seg)
            rel = "/".join(parts)

        base_path = Path(rel)

        def try_file(rel_path: str) -> str | None:
            rp = _normalize_rel(rel_path)
            if rp in self._file_index:
                return rp
            return None

        direct = try_file(rel)
        if direct:
            return direct

        for ext in _JS_TS_EXTS_TRY_ORDER:
            hit = try_file(f"{rel}{ext}")
            if hit:
                return hit

        for name in _JS_INDEX_NAMES:
            hit = try_file(f"{rel}/{name}")
            if hit:
                return hit

        for ext in _JS_TS_EXTS_TRY_ORDER:
            hit = try_file(f"{rel}/index{ext}")
            if hit:
                return hit

        stem = base_path.name
        parent = base_path.parent
        if stem:
            mod_key = ".".join([*[p for p in parent.parts if p != "."], stem])
            hit = self._pick(mod_key)
            if hit:
                return hit

        return None

    def _resolve_java(self, import_path: str) -> str | None:
        if not import_path:
            return None
        suffix = import_path.replace(".", "/") + ".java"
        for path in self._file_index:
            if path.endswith(suffix):
                return path
        return self._pick(import_path)

    def _resolve_go(self, import_path: str) -> str | None:
        imp = import_path.strip().strip('"').strip("`")
        if not imp:
            return None

        imp = imp.replace("\\", "/")
        candidates: list[str] = []
        for path in self._file_index:
            if not path.endswith(".go"):
                continue
            parent = str(Path(path).parent).replace("\\", "/")
            if parent.endswith(imp) or parent.endswith("/" + imp) or parent == imp:
                candidates.append(path)
        if not candidates:
            return None
        return sorted(candidates)[0]
