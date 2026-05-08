# tests/wiki/test_strip_fences_generic.py
from wiki.json_robust import _strip_fences


class TestStripFencesGeneric:
    def test_json_fence(self):
        assert _strip_fences('```json\n{"key": "val"}\n```') == '{"key": "val"}'

    def test_markdown_fence(self):
        assert _strip_fences('```markdown\n# Title\ncontent\n```') == '# Title\ncontent'

    def test_md_fence(self):
        assert _strip_fences('```md\n# Title\n```') == '# Title'

    def test_html_fence(self):
        assert _strip_fences('```html\n<div>hi</div>\n```') == '<div>hi</div>'

    def test_text_fence(self):
        assert _strip_fences('```text\nplain text\n```') == 'plain text'

    def test_bare_fence(self):
        assert _strip_fences('```\ncontent\n```') == 'content'

    def test_no_fence(self):
        assert _strip_fences('no fences here') == 'no fences here'

    def test_preserves_inner_fences(self):
        text = '```markdown\n# Title\n```python\ncode\n```\n```'
        result = _strip_fences(text)
        assert result.startswith('# Title')
