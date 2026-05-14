"""Deterministic compression of wiki edit conversation turns."""

from __future__ import annotations

from store.session_store import SessionTurn

# A "round" = 1 user turn + 1 assistant turn = 2 turns


def compress_turns(
    turns: list[SessionTurn],
    keep_recent_rounds: int = 3,
) -> list[SessionTurn]:
    """Compress old turns into a summary when total rounds exceed threshold.

    Rules:
    - If total rounds <= keep_recent_rounds + 1 (i.e. <= 4 rounds / 8 turns), return as-is
    - Otherwise: summarize all but the last `keep_recent_rounds` rounds
    - The summary becomes a single "system" turn at the beginning
    - Keeps the last `keep_recent_rounds` * 2 turns complete

    Returns the compressed turn list.
    """
    if len(turns) <= (keep_recent_rounds + 1) * 2:
        return turns

    keep_count = keep_recent_rounds * 2
    old_turns = turns[:-keep_count]
    recent_turns = turns[-keep_count:]

    summary_parts: list[str] = []
    for i in range(0, len(old_turns), 2):
        user_turn = old_turns[i] if i < len(old_turns) else None
        asst_turn = old_turns[i + 1] if i + 1 < len(old_turns) else None
        round_num = i // 2 + 1
        user_text = user_turn.content[:200] if user_turn else ""
        asst_text = _summarize_assistant_content(asst_turn.content if asst_turn else "")
        summary_parts.append(f"Round {round_num}: User asked: {user_text}")
        if asst_text:
            summary_parts.append(f"  Assistant: {asst_text}")

    summary = "[Earlier conversation summary]\n" + "\n".join(summary_parts)
    summary_turn = SessionTurn(role="system", content=summary)

    return [summary_turn] + recent_turns


def _summarize_assistant_content(content: str, max_chars: int = 300) -> str:
    """Extract a brief summary from assistant response content.

    If content looks like full markdown, extract just the heading changes.
    Otherwise truncate.
    """
    if not content:
        return ""
    lines = content.split("\n")
    headings = [l for l in lines if l.startswith("#")]
    if headings and len(content) > max_chars:
        return (
            "Modified page with sections: "
            + ", ".join(h.strip("# ").strip() for h in headings[:5])
        )
    return content[:max_chars]


def truncate_assistant_turn(content: str, max_chars: int = 500) -> str:
    """Truncate large assistant turn content before storing.

    Full markdown should not be stored in turns - only a summary.
    """
    if len(content) <= max_chars:
        return content
    lines = content.split("\n")
    headings = [l for l in lines if l.startswith("#")]
    if headings:
        sections = ", ".join(h.strip("# ").strip() for h in headings[:8])
        return (
            f"[Edited page - {len(content)} chars]\nSections: {sections}\n"
            f"{content[:200]}..."
        )
    return content[:max_chars] + "..."
