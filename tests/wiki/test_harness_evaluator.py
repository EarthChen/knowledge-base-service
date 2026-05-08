"""Tests for WikiPageEvaluator L1 deterministic checks."""
import pytest
from dataclasses import dataclass


@dataclass
class _FakeAssessment:
    level: str = "moderate"
    use_llm_judge: bool = False


class TestEvaluatorL1:
    def test_good_content_passes(self):
        from wiki.harness_evaluator import WikiPageEvaluator
        evaluator = WikiPageEvaluator()
        content = """## 概述
ModuleA 负责用户认证，ModuleB 负责权限校验。

## 核心业务流程
用户通过 ModuleA 进行登录验证，然后 ModuleB 检查权限。

## 关键实现
ModuleA 使用 JWT token，ModuleB 使用 RBAC 模型。

## 依赖关系
ModuleA 依赖 ModuleB 进行权限验证。
""" + "详细内容。" * 100
        result = evaluator.evaluate_l1(content, ["ModuleA", "ModuleB"])
        assert result.passed is True
        assert result.score >= 0.7
        assert len(result.issues) == 0

    def test_missing_modules_fails_coverage(self):
        from wiki.harness_evaluator import WikiPageEvaluator
        evaluator = WikiPageEvaluator()
        content = """## 概述
ModuleA 负责用户认证。
## 核心业务流程
流程说明。
""" + "填充内容。" * 100
        result = evaluator.evaluate_l1(content, ["ModuleA", "ModuleB", "ModuleC", "ModuleD", "ModuleE"])
        assert any(i.category == "coverage" for i in result.issues)

    def test_missing_overview_fails_structure(self):
        from wiki.harness_evaluator import WikiPageEvaluator
        evaluator = WikiPageEvaluator()
        content = """## 核心业务流程
ModA calls ModB.
## 关键实现
Details here.
""" + "填充。" * 100
        result = evaluator.evaluate_l1(content, ["ModA", "ModB"])
        assert any(i.category == "structure" for i in result.issues)

    def test_unclosed_fence_fails_format(self):
        from wiki.harness_evaluator import WikiPageEvaluator
        evaluator = WikiPageEvaluator()
        content = """## 概述
ModA handles auth.
## 核心业务流程
```mermaid
sequenceDiagram
  ModA->>ModB: call
""" + "填充。" * 100
        result = evaluator.evaluate_l1(content, ["ModA", "ModB"])
        assert any(i.category == "format" for i in result.issues)

    def test_too_short_fails_length(self):
        from wiki.harness_evaluator import WikiPageEvaluator
        evaluator = WikiPageEvaluator()
        content = "## 概述\nShort."
        result = evaluator.evaluate_l1(content, ["Mod"])
        assert any(i.category == "length" for i in result.issues)
        assert result.passed is False

    def test_evaluate_dispatches_to_l1_only_when_no_llm_judge(self):
        from wiki.harness_evaluator import WikiPageEvaluator
        evaluator = WikiPageEvaluator()
        content = "## 概述\nModA.\n## 核心业务流程\nflow.\n" + "x" * 600
        assessment = _FakeAssessment(level="simple", use_llm_judge=False)
        result = evaluator.evaluate(content, ["ModA"], assessment)
        assert isinstance(result.score, float)
