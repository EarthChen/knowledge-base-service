"""Fully-qualified naming and Spring/Java dependency-injection helpers for graph indexing."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from indexer.annotation_semantics import classify_annotations
from indexer.languages.java_lang import JavaPlugin
from indexer.tree_sitter_parser import ParsedField, ParseResult

if TYPE_CHECKING:
    from indexer.languages import PluginRegistry

_JAVA_SRC_MARKERS = ("src/main/java/", "src/test/java/")

_STDLIB_IMPORT_PREFIXES = (
    "java.", "javax.", "jdk.", "sun.", "com.sun.",
    "org.w3c.", "org.xml.", "org.ietf.",
)


def _is_stdlib_import(module_path: str) -> bool:
    """Return True for JDK / standard library imports that should not be indexed."""
    return module_path.startswith(_STDLIB_IMPORT_PREFIXES)


_SPRING_BEAN_SEMANTIC_ROLES = frozenset({
    "service", "repository", "component", "http_controller",
})


def _java_class_is_spring_di_bean(decorators: list[str]) -> bool:
    roles = set(classify_annotations(decorators))
    return bool(roles & _SPRING_BEAN_SEMANTIC_ROLES)


def _java_simple_type_name_from_string(ftype: str) -> str:
    t = ftype.strip()
    if not t:
        return ""
    if "<" in t:
        t = t.split("<", 1)[0].strip()
    return t.split(".")[-1]


def _java_constructors_for_class(result: ParseResult, cls_name: str) -> list:
    out = []
    for f in result.functions:
        if f.language != "java" or f.parent_class != cls_name:
            continue
        if f.name == cls_name and not (f.return_type or "").strip():
            out.append(f)
    return out


def _merge_java_constructor_injection_fields(result: ParseResult, file_path: str, language: str) -> list[ParsedField]:
    """Append ctor-parameter deps when a Spring bean has a single constructor (Lombok-free DI)."""
    if language != "java":
        return list(result.fields)
    merged = list(result.fields)
    existing = {(f.parent_class, f.name) for f in merged}
    for cls in result.classes:
        if not _java_class_is_spring_di_bean(cls.decorators):
            continue
        ctors = _java_constructors_for_class(result, cls.name)
        if len(ctors) != 1:
            continue
        ctor = ctors[0]
        for p in ctor.parameters:
            pname = (p.get("name") or "").strip()
            ptype = (p.get("type") or "").strip()
            if not pname:
                continue
            key = (cls.name, pname)
            if key in existing:
                continue
            simple = _java_simple_type_name_from_string(ptype)
            if not JavaPlugin._java_type_looks_like_spring_bean(simple):
                continue
            merged.append(ParsedField(
                name=pname,
                field_type=ptype,
                file=file_path,
                line=ctor.start_line,
                annotations=[],
                parent_class=cls.name,
                injection_type="constructor",
            ))
            existing.add(key)
    return merged


def compute_java_fqn(file_path: str, entity_name: str, is_method: bool = False, parent_class: str = "") -> str:
    """Derive a Java fully-qualified name from the file path.

    For standard Maven/Gradle layouts the package maps to the directory
    structure after ``src/main/java/`` or ``src/test/java/``.
    """
    for marker in _JAVA_SRC_MARKERS:
        idx = file_path.find(marker)
        if idx == -1:
            continue
        rel = file_path[idx + len(marker):]
        class_fqn = rel.replace("/", ".").removesuffix(".java")
        if is_method:
            if parent_class:
                return f"{class_fqn}#{entity_name}"
            pkg = class_fqn.rsplit(".", 1)[0] if "." in class_fqn else ""
            return f"{pkg}.{entity_name}" if pkg else entity_name
        return class_fqn
    return ""


def _python_module_from_file(file_path: str) -> str:
    p = Path(file_path.replace("\\", "/"))
    stem = p.stem
    dir_parts = [x for x in p.parent.parts if x not in ("/", "\\", ".", "")]
    cleaned: list[str] = []
    for x in dir_parts:
        if len(x) == 2 and x[1] == ":":
            continue
        cleaned.append(x)
    return ".".join(cleaned + [stem])


def _go_package_from_file(file_path: str) -> str:
    """Heuristic: use parent directory as Go package name.

    Limitation: real Go packages come from the `package` declaration, not
    the directory.  For a more precise FQN, parse the `package` line from
    the source file during the AST pass.
    """
    name = Path(file_path.replace("\\", "/")).parent.name
    return name if name else "main"


_JS_TS_EXTS_LONGEST_FIRST = (
    ".tsx", ".jsx", ".mjs", ".cjs", ".d.ts", ".ts", ".js",
)


def _js_ts_suffix(lower_name: str) -> str | None:
    for ext in _JS_TS_EXTS_LONGEST_FIRST:
        if lower_name.endswith(ext):
            return ext
    return None


def _js_ts_module_prefix(file_path: str) -> str:
    fp = file_path.replace("\\", "/")
    lower = fp.lower()
    ext = _js_ts_suffix(lower)
    if ext:
        return fp[: -len(ext)].lstrip("./")
    return Path(fp).with_suffix("").as_posix().lstrip("./")


def compute_fqn(
    file_path: str,
    entity_name: str,
    label: str,
    parent_class: str = "",
    *,
    registry: PluginRegistry | None = None,
) -> str:
    """Compute a stable fully-qualified–style name from file path and entity hierarchy."""
    if registry is not None:
        fp = file_path.replace("\\", "/")
        lower = fp.lower()
        plugin = None
        if lower.endswith(".java"):
            plugin = registry.get_by_extension(".java")
        elif lower.endswith(".py"):
            plugin = registry.get_by_extension(".py")
        elif lower.endswith(".go"):
            plugin = registry.get_by_extension(".go")
        else:
            js_ext = _js_ts_suffix(lower)
            if js_ext:
                plugin = registry.get_by_extension(js_ext)
            else:
                suffix = Path(fp).suffix.lower()
                if suffix:
                    plugin = registry.get_by_extension(suffix)
        if plugin is not None:
            return plugin.compute_fqn(file_path, entity_name, label, parent_class)

    if file_path.endswith(".java"):
        return compute_java_fqn(file_path, entity_name, is_method=(label == "Function"), parent_class=parent_class)

    fp = file_path.replace("\\", "/")
    lower = fp.lower()

    if lower.endswith(".py"):
        mod = _python_module_from_file(fp)
        if label == "Class":
            return f"{mod}.{entity_name}"
        if parent_class:
            return f"{mod}.{parent_class}.{entity_name}"
        return f"{mod}.{entity_name}"

    if lower.endswith(".go"):
        pkg = _go_package_from_file(fp)
        if label == "Class":
            return f"{pkg}.{entity_name}"
        if parent_class:
            return f"{pkg}.{parent_class}.{entity_name}"
        return f"{pkg}.{entity_name}"

    if _js_ts_suffix(lower):
        mod = _js_ts_module_prefix(fp)
        if label == "Class":
            return f"{mod}.{entity_name}"
        if parent_class:
            return f"{mod}.{parent_class}.{entity_name}"
        return f"{mod}.{entity_name}"

    return ""
