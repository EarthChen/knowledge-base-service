"""Shared JVM layout helpers for Java/Kotlin-style source roots."""

from __future__ import annotations

_JVM_SRC_MARKERS = (
    "src/main/java/",
    "src/test/java/",
    "src/main/kotlin/",
    "src/test/kotlin/",
)


def compute_jvm_fqn(
    file_path: str,
    entity_name: str,
    *,
    is_method: bool,
    parent_class: str,
    file_suffix: str,
) -> str:
    """Derive a JVM-style fully-qualified name from the file path.

    Maps directory structure after ``src/main/java`` / ``src/test/java`` /
    Kotlin equivalents to dotted package names, mirroring prior ``compute_java_fqn``.
    """
    suf = file_suffix if file_suffix.startswith(".") else f".{file_suffix}"
    for marker in _JVM_SRC_MARKERS:
        idx = file_path.find(marker)
        if idx == -1:
            continue
        rel = file_path[idx + len(marker) :]
        class_fqn = rel.replace("/", ".").removesuffix(suf)
        if is_method:
            if parent_class:
                return f"{class_fqn}#{entity_name}"
            pkg = class_fqn.rsplit(".", 1)[0] if "." in class_fqn else ""
            return f"{pkg}.{entity_name}" if pkg else entity_name
        return class_fqn
    return ""
