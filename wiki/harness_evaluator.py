"""Wiki page evaluator: L1 deterministic checks, L2 static benchmark, optional L3 LLM judge."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from core.log import get_logger

log = get_logger(__name__)


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
    dimensions: dict[str, float] = field(default_factory=dict)


_L3_JUDGE_PROMPT = """Evaluate this wiki page on 4 dimensions (1-5 scale each):

1. **Completeness**: Does it cover all key functionality, public APIs, data flow?
2. **Accuracy**: Are code references correct? No hallucinated entities?
3. **Readability**: Clear writing, good structure, appropriate diagrams?
4. **Structure**: Logical organization, proper heading hierarchy, navigation?

Modules covered: {modules}

Wiki content:
{content}

Output JSON only:
{{"completeness": N, "accuracy": N, "readability": N, "structure": N}}"""


class WikiPageEvaluator:
    PASS_THRESHOLD = 0.7
    MIN_CHARS = 500
    MAX_CHARS = 15000

    @staticmethod
    def _use_l2_benchmark(assessment) -> bool:
        """True when L2 static analysis should run (``use_l2_benchmark`` or deprecated ``use_llm_judge``)."""
        return bool(getattr(assessment, "use_l2_benchmark", False)) or bool(
            getattr(assessment, "use_llm_judge", False)
        )

    @staticmethod
    def should_run_l3_llm_judge(assessment, l1_result: EvalResult) -> bool:
        """L3 LLM judge runs only when enabled on assessment and L1 meets the pass threshold."""
        if not getattr(assessment, "use_l3_llm_judge", False):
            return False
        return l1_result.passed and l1_result.score >= WikiPageEvaluator.PASS_THRESHOLD

    def evaluate(self, content: str, modules: list[str], assessment, llm=None) -> EvalResult:
        l1_result = self.evaluate_l1(content, modules)
        if self._use_l2_benchmark(assessment):
            return self.evaluate_l2(content, modules, llm, l1_result)
        return l1_result

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

    def evaluate_l2(self, content, modules, llm, l1_result) -> EvalResult:
        """Static analysis benchmark: code refs, Mermaid diagrams, cross-references."""
        issues: list[Issue] = list(l1_result.issues)
        scores: list[float] = [l1_result.score]

        # Code reference coverage: backtick-quoted identifiers matching modules
        code_refs = set(re.findall(r"`([A-Za-z_]\w+)`", content))
        module_set = {m.lower() for m in modules}
        matched_refs = sum(1 for r in code_refs if r.lower() in module_set)
        ref_coverage = matched_refs / max(len(modules), 1)
        scores.append(min(1.0, ref_coverage))
        if ref_coverage < 0.5:
            issues.append(Issue(
                "code_refs",
                "warning",
                f"代码引用覆盖率 {ref_coverage:.0%}",
                "添加更多 `ModuleName` 引用",
            ))

        # Mermaid diagram presence and basic validity
        mermaid_blocks = re.findall(r"```mermaid\s*(.*?)```", content, re.DOTALL)
        has_mermaid = len(mermaid_blocks) > 0
        mermaid_valid = all(
            any(kw in block for kw in (
                "graph",
                "flowchart",
                "sequenceDiagram",
                "classDiagram",
                "stateDiagram",
            ))
            for block in mermaid_blocks
        ) if mermaid_blocks else False
        mermaid_score = 1.0 if (has_mermaid and mermaid_valid) else (0.5 if has_mermaid else 0.0)
        scores.append(mermaid_score)
        if not has_mermaid:
            issues.append(Issue("diagram", "warning", "缺少 Mermaid 架构图", "添加 ```mermaid 图表"))

        # Cross-reference links [[...]]
        cross_refs = re.findall(r"\[\[([^\]]+)\]\]", content)
        cross_ref_score = min(1.0, len(cross_refs) * 0.25)
        scores.append(cross_ref_score)
        if not cross_refs:
            issues.append(Issue("cross_refs", "info", "无交叉引用链接", "添加 [[related-module]] 链接"))

        final_score = sum(scores) / len(scores) if scores else 0.0
        return EvalResult(
            score=round(final_score, 4),
            passed=final_score >= self.PASS_THRESHOLD,
            issues=issues,
            suggestions=[i.suggestion for i in issues if i.severity == "error"],
        )

    async def evaluate_l3(
        self,
        content: str,
        modules: list[str],
        llm,
        *,
        model: str | None = None,
    ) -> EvalResult:
        """4-dimension LLM Judge evaluation (CodeWikiBench aligned)."""
        prompt = _L3_JUDGE_PROMPT.format(
            content=content[:6000],
            modules=", ".join(modules[:20]),
        )
        try:
            raw = await llm.generate(
                prompt=prompt,
                system="You are a wiki quality evaluator. Output JSON only.",
                model=model,
            )
            data = json.loads(raw.strip())
            dims = {
                "completeness": max(1.0, min(5.0, float(data.get("completeness", 1)))),
                "accuracy": max(1.0, min(5.0, float(data.get("accuracy", 1)))),
                "readability": max(1.0, min(5.0, float(data.get("readability", 1)))),
                "structure": max(1.0, min(5.0, float(data.get("structure", 1)))),
            }
            overall = sum(dims.values()) / len(dims)
            return EvalResult(
                score=overall,
                passed=overall >= 3.0,
                dimensions=dims,
            )
        except Exception:
            log.warning("evaluate_l3_failed", exc_info=True)
            return EvalResult(score=0.0, passed=False, dimensions={})
