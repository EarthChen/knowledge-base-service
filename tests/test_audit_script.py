"""Tests for scripts/audit_wiki_data.py helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_wiki_data.py"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_wiki_data", _SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_wiki_data"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def audit_mod():
    return _load_audit_module()


def test_compute_cn_ratio_chinese_text(audit_mod):
    ratio = audit_mod._compute_cn_ratio("这是一段纯中文内容用于测试比例计算")
    assert ratio == 1.0


def test_compute_cn_ratio_english_text(audit_mod):
    ratio = audit_mod._compute_cn_ratio("This is pure English content for testing.")
    assert ratio == 0.0


def test_compute_cn_ratio_mixed(audit_mod):
    ratio = audit_mod._compute_cn_ratio("Hello 你好 world 世界")
    assert 0.0 < ratio < 1.0


def test_compute_cn_ratio_strips_code_fences(audit_mod):
    content = "中文正文\n```python\ndef foo():\n    return 'english only'\n```\n更多中文"
    ratio = audit_mod._compute_cn_ratio(content)
    assert ratio > 0.5


def test_compute_cn_ratio_empty(audit_mod):
    assert audit_mod._compute_cn_ratio("") == 0.0
    assert audit_mod._compute_cn_ratio(None) == 0.0  # type: ignore[arg-type]
