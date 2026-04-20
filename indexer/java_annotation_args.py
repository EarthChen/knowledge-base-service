"""Shared Java annotation argument extraction for indexers."""

from __future__ import annotations

import re


def extract_java_annotation_primary_arg(annotation: str) -> str:
    """Extract a primary value from a Java-style annotation body.

    Order:
    1. ``serviceUri = "..."`` or ``uri = "..."`` (Moa RPC; avoids misparsing when other
       string attrs like ``protocol`` appear first).
    2. First quoted string literal in the argument list.
    3. First ``name = "quoted"`` style value.
    4. ``interfaceClass = com.foo.SomeIface.class`` (or simple ``SomeIface.class``) →
       returns the **simple** type name (``SomeIface``) for RPC matching.
    """
    s = annotation.strip()
    start = s.find("(")
    if start == -1:
        return ""
    depth = 0
    end = -1
    for i in range(start, len(s)):
        ch = s[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        return ""
    inner = s[start + 1 : end]
    # Moa: ``serviceUri`` / ``uri`` must win over earlier string args (e.g. ``protocol = "tcp"``).
    m0 = re.search(r"\b(?:serviceUri|uri)\s*=\s*[\"']((?:[^\"'\\]|\\.)*)[\"']", inner, re.IGNORECASE)
    if m0:
        return m0.group(1)
    m = re.search(r'["\']((?:[^"\'\\]|\\.)*)["\']', inner)
    if m:
        return m.group(1)
    m2 = re.search(r'=\s*["\']((?:[^"\'\\]|\\.)*)["\']', inner)
    if m2:
        return m2.group(1)
    m3 = re.search(
        r"\binterfaceClass\s*=\s*([\w.$]+)\s*\.\s*class\b",
        inner,
        re.IGNORECASE,
    )
    if m3:
        raw_type = m3.group(1).strip()
        return raw_type.rsplit(".", 1)[-1].replace("$", ".")
    return ""
