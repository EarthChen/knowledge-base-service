# tests/wiki/test_context_gap.py
from wiki.context_gap import CONTEXT_GAP_RE, CONTEXT_GAP_DETECT_RE, cleanup_context_gaps


class TestContextGapRegex:
    def test_english_colon(self):
        text = "before <!-- CONTEXT_GAP: missing info --> after"
        assert CONTEXT_GAP_DETECT_RE.findall(text) == ["missing info"]

    def test_chinese_colon(self):
        text = "before <!-- CONTEXT_GAP：已补充信息 --> after"
        assert CONTEXT_GAP_DETECT_RE.findall(text) == ["已补充信息"]

    def test_space_separator(self):
        text = "before <!-- CONTEXT_GAP 已补充：详细内容 --> after"
        assert CONTEXT_GAP_DETECT_RE.findall(text) == ["已补充：详细内容"]

    def test_multiline(self):
        text = "before <!-- CONTEXT_GAP: line1\nline2 --> after"
        assert len(CONTEXT_GAP_DETECT_RE.findall(text)) == 1

    def test_no_separator(self):
        text = "before <!-- CONTEXT_GAP --> after"
        assert CONTEXT_GAP_RE.search(text) is not None

    def test_cleanup_removes_marker(self):
        text = "before <!-- CONTEXT_GAP: missing --> after"
        result = cleanup_context_gaps(text)
        assert "CONTEXT_GAP" not in result
        assert "此处信息待补充" not in result
        assert "missing" not in result
        assert "before" in result
        assert "after" in result

    def test_cleanup_multiline(self):
        text = "before <!-- CONTEXT_GAP: line1\nline2 --> after"
        result = cleanup_context_gaps(text)
        assert "CONTEXT_GAP" not in result

    def test_cleanup_empty_marker(self):
        text = "before <!-- CONTEXT_GAP --> after"
        result = cleanup_context_gaps(text)
        assert "<!-- CONTEXT_GAP" not in result
