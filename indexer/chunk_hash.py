"""SHA-256 content hashes for embeddable graph nodes (chunk-level incremental indexing)."""

from __future__ import annotations

import hashlib

from .embedding_text_format import _format_code_text, _format_doc_text, doc_dict_for_embedding
from store.schema import GraphNode, NodeLabel

def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_text_for_embed_hash(node: GraphNode) -> str:
    """Text used to compute *content_hash* (matches embedding input, except volatile LLM fields).

    *business_summary* is excluded so summary-only changes do not invalidate the
    code/doc body hash. Embedding still merges business_summary at runtime when present.
    """
    label = node.label
    p = node.properties

    if label == NodeLabel.CHUNK:
        raw = p.get("text", "")
        t = raw if isinstance(raw, str) else str(raw)
        return _format_code_text("", "", "", t, "")

    if label in (NodeLabel.FUNCTION, NodeLabel.CLASS):
        name = str(p.get("name", "") or "")
        sig = str(p.get("signature", "") or "")
        doc = str(p.get("docstring", "") or "")
        code = str(p.get("code_snippet", "") or "")
        return _format_code_text(name, sig, doc, code, "")

    if label == NodeLabel.DOCUMENT:
        d = doc_dict_for_embedding(p)
        title = d.get("title", "") or ""
        section = d.get("section", "") or ""
        content = d.get("content", "") or ""
        hc = d.get("heading_context", "") or ""
        return _format_doc_text(title, section, content, hc)

    return ""


def content_hash_for_node(node: GraphNode) -> str | None:
    """Return SHA-256 hex digest for an embeddable node, or *None* if not hashed."""
    if node.label not in (
        NodeLabel.FUNCTION,
        NodeLabel.CLASS,
        NodeLabel.DOCUMENT,
        NodeLabel.CHUNK,
    ):
        return None
    body = canonical_text_for_embed_hash(node)
    return _sha256_hex(body)


def apply_content_hash_to_nodes(nodes: list[GraphNode]) -> None:
    """Set ``content_hash`` on every embeddable node in *nodes* (mutates in place)."""
    for n in nodes:
        h = content_hash_for_node(n)
        if h is not None:
            n.properties["content_hash"] = h
