from store.session_store import SessionTurn
from wiki.agents.turn_compressor import (
    _summarize_assistant_content,
    compress_turns,
    truncate_assistant_turn,
)


def _rounds(n_pairs: int, prefix: str = "") -> list[SessionTurn]:
    out: list[SessionTurn] = []
    for i in range(n_pairs):
        out.append(SessionTurn(role="user", content=f"{prefix}u{i}"))
        out.append(SessionTurn(role="assistant", content=f"{prefix}a{i}"))
    return out


def test_compress_turns_short_keeps_all():
    turns = _rounds(2)
    out = compress_turns(turns)
    assert out is turns


def test_compress_turns_threshold():
    turns = _rounds(4)
    out = compress_turns(turns)
    assert len(out) == 8
    assert out is turns


def test_compress_turns_over_threshold():
    turns = _rounds(5)
    out = compress_turns(turns)
    assert len(out) == 7
    assert out[0].role == "system"
    assert "Round 1: User asked: u0" in out[0].content
    assert "Assistant: a0" in out[0].content
    assert "Round 2: User asked: u1" in out[0].content
    assert out[-2].content == "u4"
    assert out[-1].content == "a4"


def test_compress_turns_summary_format():
    turns = _rounds(5, prefix="x")
    out = compress_turns(turns)
    assert out[0].role == "system"
    assert "[Earlier conversation summary]" in out[0].content


def test_compress_turns_keeps_recent():
    turns = _rounds(5, prefix="DISTINCT_")
    out = compress_turns(turns)
    kept = out[1:]
    assert len(kept) == 6
    assert [t.role for t in kept] == ["user", "assistant"] * 3
    expected = [
        "DISTINCT_u2",
        "DISTINCT_a2",
        "DISTINCT_u3",
        "DISTINCT_a3",
        "DISTINCT_u4",
        "DISTINCT_a4",
    ]
    assert [t.content for t in kept] == expected


def test_summarize_assistant_content_short():
    text = "Brief reply"
    assert _summarize_assistant_content(text) == text


def test_summarize_assistant_content_markdown():
    body = "\n".join(["# One", "# Two", "## Three", "para " * 80])
    assert len(body) > 300
    summary = _summarize_assistant_content(body)
    assert summary.startswith("Modified page with sections:")
    assert "One" in summary and "Two" in summary


def test_truncate_assistant_turn_short():
    text = "# Short\nok"
    assert truncate_assistant_turn(text) == text


def test_truncate_assistant_turn_long_markdown():
    big = "\n".join([f"## Section {i}" for i in range(20)] + ["body " * 200])
    out = truncate_assistant_turn(big, max_chars=500)
    assert out.startswith("[Edited page -")
    assert "Sections:" in out
