"""Wiki page evaluator with L1 deterministic checks and optional L2 LLM judge."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Issue:
    category: str
    severity: str
    message: str
    suggestion: str = ""


@dataclass
class EvalResult:
    score: float
    passed: bool
    issues: list[Issue] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


class WikiPageEvaluator:
    PASS_THRESHOLD = 0.7
    MIN_CHARS = 500
    MAX_CHARS = 15000

    def evaluate(self, content: str, modules: list[str], assessment, llm=None) -> EvalResult:
        result = self.evaluate_l1(content, modules)
        if getattr(assessment, "use_llm_judge", False) and not result.passed and llm:
            result = self.evaluate_l2(content, modules, llm, result)
        return result

    def evaluate_l1(self, content: str, modules: list[str]) -> EvalResult:
        issues: list[Issue] = []
        scores: list[float] = []

        # 1. Module coverage
        if modules:
            mentioned = sum(1 for m in modules if m.lower() in content.lower())
            coverage = mentioned / len(modules)
        else:
            coverage = 1.0
        scores.append(coverage)
        if coverage < 0.8:
            missing = [m for m in modules if m.lower() not in content.lower()]
            issues.append(Issue(
                category="coverage", severity="error",
                message=f"模块覆盖率 {coverage:.0%}, 缺失: {missing[:5]}",
                suggestion="请确保提及所有关键模块",
            ))

        # 2. Structure
        has_overview = bool(re.search(r"^##?\s*(概述|Overview)", content, re.M))
        has_flow = bool(re.search(r"^##?\s*(核心|业务|流程|Core|Flow)", content, re.M))
        struct_score = (int(has_overview) + int(has_flow)) / 2
        scores.append(struct_score)
        if not has_overview:
            issues.append(Issue("structure", "error", "缺少概述段", "添加## 概述"))
        if not has_flow:
            issues.append(Issue("structure", "warning", "缺少业务流程段", "添加## 核心业务流程"))

        # 3. Format
        has_unclosed_fence = content.count("```") % 2 != 0
        has_context_gap = "CONTEXT_GAP" in content
        format_score = 1.0 - (0.3 * int(has_unclosed_fence) + 0.2 * int(has_context_gap))
        scores.append(format_score)
        if has_unclosed_fence:
            issues.append(Issue("format", "error", "未关闭的代码块", "检查```配对"))
        if has_context_gap:
            issues.append(Issue("format", "warning", "存在CONTEXT_GAP标记", "补充缺失信息"))

        # 4. Length
        char_count = len(content)
        if char_count < self.MIN_CHARS:
            length_score = char_count / self.MIN_CHARS
            issues.append(Issue("length", "error", f"内容过短({char_count}字)", "补充更多细节"))
        elif char_count > self.MAX_CHARS:
            length_score = 0.8
            issues.append(Issue("length", "warning", f"内容过长({char_count}字)", "精简冗余"))
        else:
            length_score = 1.0
        scores.append(length_score)

        final_score = sum(scores) / len(scores) if scores else 0.0
        return EvalResult(
            score=final_score,
            passed=final_score >= self.PASS_THRESHOLD,
            issues=issues,
            suggestions=[i.suggestion for i in issues if i.severity == "error"],
        )

    async def evaluate_l2(self, content, modules, llm, l1_result) -> EvalResult:
        """LLM Judge — fallback to L1 result for now."""
        return l1_result
