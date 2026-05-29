from __future__ import annotations


def micro_compact(messages: list[dict], *, keep_recent_n: int = 3) -> list[dict]:
    """L1: Clear old tool results, keep recent N. Remove orphan tool_calls."""
    tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    keep_set = set(tool_indices[-keep_recent_n:]) if len(tool_indices) > keep_recent_n else set(tool_indices)

    result: list[dict] = []
    for i, msg in enumerate(messages):
        if msg.get("role") == "tool":
            if i in keep_set:
                result.append(msg)
            else:
                n_chars = len(msg.get("content", ""))
                result.append({**msg, "content": f"[已压缩: tool result, {n_chars} chars]"})
        else:
            result.append(msg)

    all_tool_result_ids = {m.get("tool_call_id") for m in messages if m.get("role") == "tool"}
    cleaned: list[dict] = []
    for msg in result:
        if tcs := msg.get("tool_calls"):
            valid = [tc for tc in tcs if tc.get("id") in all_tool_result_ids]
            if valid:
                cleaned.append({**msg, "tool_calls": valid})
            elif msg.get("content"):
                cleaned.append({k: v for k, v in msg.items() if k != "tool_calls"})
        else:
            cleaned.append(msg)

    return cleaned


def snip_compact(messages: list[dict], *, max_tool_chars: int = 2000) -> list[dict]:
    """L2: Truncate long tool results to head+tail format."""
    result: list[dict] = []
    for msg in messages:
        if msg.get("role") == "tool" and len(msg.get("content", "")) > max_tool_chars:
            content = msg["content"]
            head = content[:500]
            tail = content[-500:]
            result.append({**msg, "content": f"{head}\n...[snipped {len(content)} chars]...\n{tail}"})
        else:
            result.append(msg)

    return result
