"""Tests for WikiPageEvaluator L1 deterministic checks."""
import pytest
from dataclasses import dataclass


@dataclass
class _FakeAssessment:
    level: str = "moderate"
    use_l2_benchmark: bool = False
    use_llm_judge: bool = False  # deprecated; OR-ed with use_l2_benchmark in evaluate()
    use_l3_llm_judge: bool = False


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

    def test_evaluate_dispatches_to_l1_only_when_no_l2_benchmark(self):
        from wiki.harness_evaluator import WikiPageEvaluator
        evaluator = WikiPageEvaluator()
        content = "## 概述\nModA.\n## 核心业务流程\nflow.\n" + "x" * 600
        assessment = _FakeAssessment(level="simple", use_l2_benchmark=False)
        result = evaluator.evaluate(content, ["ModA"], assessment)
        assert isinstance(result.score, float)

    def test_evaluate_runs_l2_when_l1_passes_if_use_l2_benchmark(self):
        """L2 static benchmark must run even when L1 passes (not only on L1 failure)."""
        from wiki.harness_evaluator import WikiPageEvaluator

        evaluator = WikiPageEvaluator()
        content = """## 概述
ModA 负责用户认证，ModB 负责权限校验。

## 核心业务流程
用户通过 ModA 进行登录验证，然后 ModB 检查权限。

## 关键实现
ModA 使用 JWT token，ModB 使用 RBAC 模型。
""" + "详细内容。" * 100
        assessment = _FakeAssessment(use_l2_benchmark=True)
        result = evaluator.evaluate(content, ["ModA", "ModB"], assessment)
        # L2 adds diagram / cross-ref signals when missing; L1-only passing page has no Mermaid.
        assert any(i.category == "diagram" for i in result.issues)

    def test_evaluate_backward_compat_use_llm_judge_alias_for_l2(self):
        from wiki.harness_evaluator import WikiPageEvaluator

        evaluator = WikiPageEvaluator()
        content = """## 概述
ModA 负责用户认证，ModB 负责权限校验。

## 核心业务流程
流程说明。

## 关键实现
细节。
""" + "详细内容。" * 100
        assessment = _FakeAssessment(use_l2_benchmark=False, use_llm_judge=True)
        result = evaluator.evaluate(content, ["ModA", "ModB"], assessment)
        assert any(i.category == "diagram" for i in result.issues)

    def test_should_run_l3_llm_judge_requires_flag_and_l1_pass(self):
        from wiki.harness_evaluator import EvalResult, WikiPageEvaluator

        passed = EvalResult(score=0.9, passed=True)
        failed = EvalResult(score=0.3, passed=False)
        on = _FakeAssessment(use_l3_llm_judge=True)
        off = _FakeAssessment(use_l3_llm_judge=False)
        assert WikiPageEvaluator.should_run_l3_llm_judge(on, passed) is True
        assert WikiPageEvaluator.should_run_l3_llm_judge(on, failed) is False
        assert WikiPageEvaluator.should_run_l3_llm_judge(off, passed) is False


def test_evaluate_l2_scores_code_coverage():
    """L2 should score based on code block references, Mermaid diagrams, and cross-refs."""
    from wiki.harness_evaluator import WikiPageEvaluator

    evaluator = WikiPageEvaluator()

    content_good = """# Auth Module

## 概述
Handles authentication via `AuthService`.

## 核心业务流程
```mermaid
graph TD
    A[Login] --> B[Validate]
    B --> C[Token]
```

Key classes: `AuthService`, `TokenManager`, `UserValidator`

See also: [[token-service]], [[user-module]]
"""

    content_bad = """# Auth Module

## 概述
Some overview without code references.

## 核心业务流程
Login flow.
"""

    modules = ["AuthService", "TokenManager", "UserValidator"]
    l1_good = evaluator.evaluate_l1(content_good, modules)
    l1_bad = evaluator.evaluate_l1(content_bad, modules)

    l2_good = evaluator.evaluate_l2(content_good, modules, None, l1_good)
    l2_bad = evaluator.evaluate_l2(content_bad, modules, None, l1_bad)

    assert l2_good.score > l2_bad.score
    assert l2_good.score > 0.5
