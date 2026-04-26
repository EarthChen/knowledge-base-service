"""Template-based exploration question generator for wiki pages."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PageContext:
    """Graph context for a wiki page entity."""
    entity_name: str
    domain: str
    callers: list[str] = field(default_factory=list)
    callees: list[str] = field(default_factory=list)
    cross_domain_callers: list[str] = field(default_factory=list)


class SuggestedQuestionsGenerator:
    """Generates exploration questions based on graph topology."""

    def __init__(self, max_questions: int = 5) -> None:
        self._max = max(0, max_questions)

    def generate(self, ctx: PageContext) -> list[str]:
        questions: list[str] = []

        if ctx.cross_domain_callers:
            domains = ", ".join(ctx.cross_domain_callers[:3])
            questions.append(
                f"{ctx.entity_name} 被跨域组件（{domains}）调用，"
                f"是否存在过度耦合或需要抽象为共享服务？"
            )

        if len(ctx.callers) >= 3:
            questions.append(
                f"{ctx.entity_name} 有 {len(ctx.callers)} 个调用方，"
                f"哪些是核心业务路径，哪些是辅助调用？"
            )

        if ctx.callees:
            deps = ", ".join(ctx.callees[:3])
            questions.append(
                f"{ctx.entity_name} 依赖 {deps} 等组件，"
                f"如果其中一个故障，降级策略是什么？"
            )

        if ctx.domain:
            questions.append(
                f"在 {ctx.domain} 领域中，{ctx.entity_name} 承担的核心职责是什么？"
                f"是否有职责边界不清晰的情况？"
            )

        if not questions:
            questions.append(
                f"{ctx.entity_name} 的设计意图和主要使用场景是什么？"
            )

        return questions[: self._max]
