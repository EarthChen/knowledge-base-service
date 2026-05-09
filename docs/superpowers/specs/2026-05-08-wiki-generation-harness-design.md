# Wiki Generation Harness 设计规格

**状态**: Draft → Review
**创建时间**: 2026-05-08
**方法论**: Brainstorming → Sequential Thinking Deep Review
**范围**: Phase 1 (评估基建+核心护栏) + Phase 2 前半 (工具增强+上下文连续性)
**前置文档**: `2026-05-08-wiki-agent-driven-enhancement-analysis.md`

---

## 1. 问题陈述

### 1.1 当前架构

```
compose.py → CCB → AgentConfig.should_use_agent?
  → YES: WikiPageAgent.generate(modules, domain, baseline_context, max_rounds=5)
           └─ tool loop (up to MAX_ROUNDS) → fallback generate → skeleton
  → NO: TopicPageComposer → WikiPageAgent.enrich(CONTEXT_GAP pages)
```

### 1.2 核心问题

| 问题 | 影响 |
|------|------|
| Agent 同时规划+生成+自评 | 自评分偏差, 遗漏不自知 |
| 工具调用随机探索 | 关键信息遗漏 (如未查调用链却生成了调用链段落) |
| 所有工具响应累积在 context | Token 浪费 (~41K/页), 信息利用率仅 ~40% |
| 无跨域知识传递 | 域间引用不一致, 重复描述 |
| 无修复机制 | 质量门控是事后的, Agent 无机会自修正 |
| compose.py 未传 repo_path/search_service | Agent-driven 路径下文件/语义工具不可用 |

### 1.3 目标

| 指标 | 当前 | 目标 |
|------|------|------|
| Token 消耗/页 | ~41K | ~15-35K (-30~60%) |
| 信息利用率 | ~40% | ~80% |
| 模块覆盖率 | 未测量 | ≥95% |
| 跨域一致性 | 无机制 | DomainSummaryCard |
| 修复机会 | 0 (事后 heal) | 2 rounds in-loop |
| 文件/语义工具可用 | ❌ | ✅ |

---

## 2. 架构概览

### 2.1 核心流程

```
compose.py: _compose_single_leaf_domain(leaf)
  │
  ├─ CCB Context Building (已有, 不变)
  │     └─ format_summary_for_agent(max_chars=6000)
  │
  └─ WikiGenerationHarness.run(domain, modules, ccb_context)
       │
       ├─ 1. AdaptiveRouter.assess(modules, ccb_context)
       │     └→ ComplexityAssessment(level, max_tool_calls, gen_mode, max_repair)
       │
       ├─ 2. WikiPagePlanner.plan(domain, modules, ccb_context, assessment)
       │     └→ GenerationPlan(outline, queries, cross_domain_refs, budget)
       │
       ├─ 3. Gather Phase: execute planned queries → GatheredFacts
       │     └─ 不使用 LLM, 按计划执行工具调用
       │     └─ 结果存入 GatheredFacts dict (不占 LLM context)
       │
       ├─ 4. Distill Phase: GatheredFacts → DistilledContext
       │     └─ 去重 + 截断 + 按section分组
       │     └─ 注入跨域 DomainSummaryCards
       │
       ├─ 5. Generate Phase: WikiPageAgent.generate(distilled_context)
       │     └─ simple: 整页一次性生成
       │     └─ complex: 按section分段生成 + Coherence Pass
       │
       ├─ 6. Evaluate Phase: WikiPageEvaluator.evaluate(content, modules)
       │     ├─ L1: 确定性检查 (模块覆盖、结构、格式、字数)
       │     └─ L2: LLM Judge (仅 complex 且 L1 失败时)
       │
       └─ 7. Repair Loop (MAX 2 rounds)
             IF score < threshold:
               Generator.repair(content, issues, suggestions)
               Evaluator.evaluate(repaired_content)
             ELSE: return content
```

### 2.2 配置开关

```python
# 环境变量
WIKI__USE_HARNESS: bool = False          # 启用 Harness (vs 直接 Agent)
WIKI__HARNESS_MAX_REPAIR_ROUNDS: int = 2 # 最大修复轮次 (全局上限)
WIKI__HARNESS_SIMPLE_THRESHOLD: int = 5  # 简单域模块数阈值
WIKI__HARNESS_COMPLEX_THRESHOLD: int = 15 # 复杂域模块数阈值
WIKI__HARNESS_LLM_JUDGE: bool = True     # 是否启用 LLM Judge (仅对 complex)
```

**Config 与 Router 的关系**: `WIKI__HARNESS_MAX_REPAIR_ROUNDS` 是全局上限，AdaptiveRouter 根据复杂度分配具体值（simple=0, moderate=1, complex=2），但不超过全局上限。

### 2.3 Fallback 策略

```
Harness 启用 → Harness.run() 失败 (超时/异常)
  → 降级到现有 WikiPageAgent.generate() (直接模式)
  → 仍然失败
  → skeleton fallback (已有)
```

---

## 3. 组件详细设计

### 3.1 AdaptiveRouter (`wiki/harness_router.py`)

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class ComplexityAssessment:
    level: Literal["simple", "moderate", "complex"]
    max_tool_calls: int
    generation_mode: Literal["whole_page", "sectional"]
    max_repair_rounds: int
    use_llm_judge: bool

class AdaptiveRouter:
    def __init__(self, simple_threshold: int = 5, complex_threshold: int = 15):
        self.simple_threshold = simple_threshold
        self.complex_threshold = complex_threshold

    def assess(self, modules: list[str], ccb_context) -> ComplexityAssessment:
        module_count = len(modules)
        edge_count = len(ccb_context.cross_domain_calls) if ccb_context else 0
        entity_count = sum(
            len(s.get("methods", [])) for s in (ccb_context.module_summaries or [])
        )

        if module_count <= self.simple_threshold and edge_count < 5:
            return ComplexityAssessment(
                level="simple", max_tool_calls=5,
                generation_mode="whole_page", max_repair_rounds=0,
                use_llm_judge=False,
            )
        elif module_count > self.complex_threshold or edge_count > 20:
            return ComplexityAssessment(
                level="complex", max_tool_calls=15,
                generation_mode="sectional", max_repair_rounds=2,
                use_llm_judge=True,
            )
        else:
            return ComplexityAssessment(
                level="moderate", max_tool_calls=10,
                generation_mode="whole_page", max_repair_rounds=1,
                use_llm_judge=False,
            )
```

### 3.2 WikiPagePlanner (`wiki/harness_planner.py`)

```python
from dataclasses import dataclass, field

@dataclass
class PlannedQuery:
    tool_name: str          # "query_call_chain", "query_module_detail", etc.
    params: dict            # 工具参数
    target_section: str     # 此查询服务于哪个 section
    priority: int           # 1=必须, 2=推荐, 3=可选

@dataclass
class SectionPlan:
    name: str                          # "概述" / "核心业务流程" / ...
    queries: list[PlannedQuery] = field(default_factory=list)
    description: str = ""              # section 应包含什么

@dataclass
class GenerationPlan:
    outline: list[SectionPlan]
    cross_domain_refs: list[str]       # 需要引用的其他域名
    total_queries: int = 0
    context_budget_tokens: int = 0

class WikiPagePlanner:
    SECTION_TEMPLATES = [
        ("概述", "模块职责、核心类/接口"),
        ("核心业务流程", "调用链、Mermaid sequenceDiagram"),
        ("关键实现", "核心方法实现、设计模式"),
        ("依赖关系", "模块间依赖、接口实现关系"),
    ]

    def plan(self, domain: str, modules: list[str],
             ccb_context, assessment: ComplexityAssessment,
             domain_cache: dict | None = None) -> GenerationPlan:
        """生成查询计划。纯确定性逻辑, 不调用LLM。"""
        sections = []
        for name, desc in self.SECTION_TEMPLATES:
            queries = self._plan_section_queries(name, modules, ccb_context, assessment)
            sections.append(SectionPlan(name=name, queries=queries, description=desc))

        cross_refs = self._identify_cross_domain_refs(ccb_context, domain_cache)

        return GenerationPlan(
            outline=sections,
            cross_domain_refs=cross_refs,
            total_queries=sum(len(s.queries) for s in sections),
            context_budget_tokens=self._calc_budget(assessment),
        )

    def _plan_section_queries(self, section_name, modules, ccb_context, assessment):
        """根据 section 类型生成查询计划。"""
        queries = []
        if section_name == "概述":
            for m in modules[:assessment.max_tool_calls // 4]:
                queries.append(PlannedQuery(
                    tool_name="query_module_detail", params={"module_name": m},
                    target_section="概述", priority=1,
                ))
        elif section_name == "核心业务流程":
            queries.append(PlannedQuery(
                tool_name="query_call_chain",
                params={"module_names": modules[:10]},
                target_section="核心业务流程", priority=1,
            ))
            # 如果有跨域调用, 查询 callers/callees
            if ccb_context and ccb_context.cross_domain_calls:
                queries.append(PlannedQuery(
                    tool_name="query_callers",
                    params={"module_names": modules[:5]},
                    target_section="核心业务流程", priority=2,
                ))
        elif section_name == "关键实现":
            if assessment.level != "simple":
                queries.append(PlannedQuery(
                    tool_name="read_code",
                    params={"module_names": modules[:3]},
                    target_section="关键实现", priority=2,
                ))
        elif section_name == "依赖关系":
            queries.append(PlannedQuery(
                tool_name="query_domain_dependencies",
                params={"domain_name": modules[0]},
                target_section="依赖关系", priority=1,
            ))
            queries.append(PlannedQuery(
                tool_name="query_implementations",
                params={"module_names": modules[:10]},
                target_section="依赖关系", priority=2,
            ))
        return queries
```

### 3.3 GatheredFacts + Distill (`wiki/harness_facts.py`)

```python
from dataclasses import dataclass, field

@dataclass
class Fact:
    source: str          # "query_call_chain"
    content: str         # 工具返回的原始内容
    section: str         # 属于哪个 section
    char_count: int = 0  # 字符数

@dataclass
CONTEXT_BUDGETS = {
    "simple": {
        "max_chars_per_section": 1500,
        "distill_total": 6000,
        "coherence_pass": None,
        "repair_input": 3000,
        "eval_input": 1500,
    },
    "moderate": {
        "max_chars_per_section": 3000,
        "distill_total": 12000,
        "coherence_pass": None,
        "repair_input": 4000,
        "eval_input": 2000,
    },
    "complex": {
        "max_chars_per_section": 5000,
        "distill_total": 20000,
        "coherence_pass": 8000,
        "repair_input": 6000,
        "eval_input": 3000,
    },
}

class GatheredFacts:
    facts: dict[str, list[Fact]] = field(default_factory=dict)  # section -> facts
    total_chars: int = 0

    def add(self, section: str, source: str, content: str):
        if section not in self.facts:
            self.facts[section] = []
        fact = Fact(source=source, content=content, section=section, char_count=len(content))
        self.facts[section].append(fact)
        self.total_chars += len(content)

    def distill(self, complexity_level: str = "moderate",
                domain_summaries: list[str] | None = None) -> str:
        """将采集的原始事实精简为生成用上下文。确定性逻辑。
        预算由 complexity_level 决定 (分级预算模式)。"""
        budget = CONTEXT_BUDGETS[complexity_level]
        max_chars_per_section = budget["max_chars_per_section"]

        sections = []
        for section_name, facts in self.facts.items():
            combined = "\n".join(f.content for f in facts)
            if len(combined) > max_chars_per_section:
                combined = combined[:max_chars_per_section] + "\n[...truncated]"
            sections.append(f"## {section_name}\n{combined}")

        result = "\n\n".join(sections)

        # 注入跨域摘要
        if domain_summaries:
            cross_ref = "\n".join(domain_summaries)
            result = f"## 相关域参考\n{cross_ref}\n\n{result}"

        return result
```

### 3.4 WikiPageEvaluator (`wiki/harness_evaluator.py`)

```python
from dataclasses import dataclass, field
import re

@dataclass
class Issue:
    category: str     # "coverage", "structure", "format", "length"
    severity: str     # "error", "warning"
    message: str
    suggestion: str = ""

@dataclass
class EvalResult:
    score: float              # 0.0 - 1.0
    passed: bool
    issues: list[Issue] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

class WikiPageEvaluator:
    PASS_THRESHOLD = 0.7
    MIN_WORDS = 500
    MAX_WORDS = 15000

    def evaluate(self, content: str, modules: list[str],
                 assessment, llm=None) -> EvalResult:
        """主评估入口。"""
        result = self.evaluate_l1(content, modules)
        if assessment.use_llm_judge and not result.passed and llm:
            result = self.evaluate_l2(content, modules, llm, result)
        return result

    def evaluate_l1(self, content: str, modules: list[str]) -> EvalResult:
        """确定性检查。0 token 消耗。"""
        issues = []
        scores = []

        # 1. 模块覆盖率检查
        mentioned = sum(1 for m in modules if m.lower() in content.lower())
        coverage = mentioned / len(modules) if modules else 1.0
        scores.append(coverage)
        if coverage < 0.8:
            issues.append(Issue(
                category="coverage", severity="error",
                message=f"模块覆盖率 {coverage:.0%}, 缺失: {[m for m in modules if m.lower() not in content.lower()][:5]}",
                suggestion="请确保提及所有关键模块",
            ))

        # 2. 结构完整性检查
        has_overview = bool(re.search(r"^##?\s*(概述|Overview)", content, re.M))
        has_flow = bool(re.search(r"^##?\s*(核心|业务|流程|Core|Flow)", content, re.M))
        struct_score = (int(has_overview) + int(has_flow)) / 2
        scores.append(struct_score)
        if not has_overview:
            issues.append(Issue("structure", "error", "缺少概述段", "添加## 概述"))
        if not has_flow:
            issues.append(Issue("structure", "warning", "缺少业务流程段", "添加## 核心业务流程"))

        # 3. 格式检查
        has_unclosed_fence = content.count("```") % 2 != 0
        has_context_gap = "CONTEXT_GAP" in content
        format_score = 1.0 - (0.3 * has_unclosed_fence + 0.2 * has_context_gap)
        scores.append(format_score)
        if has_unclosed_fence:
            issues.append(Issue("format", "error", "未关闭的代码块", "检查```配对"))
        if has_context_gap:
            issues.append(Issue("format", "warning", "存在CONTEXT_GAP标记", "补充缺失信息"))

        # 4. 字数检查
        word_count = len(content)
        length_score = 1.0
        if word_count < self.MIN_WORDS:
            length_score = word_count / self.MIN_WORDS
            issues.append(Issue("length", "error", f"内容过短({word_count}字)", "补充更多细节"))
        elif word_count > self.MAX_WORDS:
            length_score = 0.8
            issues.append(Issue("length", "warning", f"内容过长({word_count}字)", "精简冗余"))
        scores.append(length_score)

        final_score = sum(scores) / len(scores)
        return EvalResult(
            score=final_score,
            passed=final_score >= self.PASS_THRESHOLD,
            issues=issues,
            suggestions=[i.suggestion for i in issues if i.severity == "error"],
        )

    async def evaluate_l2(self, content, modules, llm, l1_result) -> EvalResult:
        """LLM Judge。仅对 complex 域且 L1 失败时触发。
        实现细节见实施计划。核心逻辑:
        - 独立 prompt, 不与 Generator 共享上下文 (消除自评分偏差)
        - 评分维度: accuracy(1-5), completeness(1-5), readability(1-5)
        - 返回结构化 JSON, 解析为 EvalResult
        - 若 LLM 调用失败, fallback 到 L1 结果
        """
        prompt = f"""评估以下 Wiki 页面质量 (1-5分):
模块列表: {modules[:10]}
页面内容 (前2000字):
{content[:2000]}

评分维度: accuracy(准确性), completeness(完整性), readability(可读性)
返回JSON: {{"accuracy": N, "completeness": N, "readability": N, "issues": ["..."]}}"""
        # 实现: await llm.generate([{"role":"user","content":prompt}]) → parse JSON → EvalResult
        pass  # 实现细节见实施计划
```

### 3.5 WikiGenerationHarness (`wiki/harness.py`)

```python
from core.log import get_logger
log = get_logger(__name__)

class WikiGenerationHarness:
    def __init__(self, agent, graph_store, llm, config=None):
        self.agent = agent
        self.graph_store = graph_store
        self.llm = llm
        self.router = AdaptiveRouter()
        self.planner = WikiPagePlanner()
        self.evaluator = WikiPageEvaluator()
        self.domain_cache: dict[str, str] = {}  # domain -> summary card

    async def run(self, domain: str, modules: list[str],
                  ccb_context, **kwargs) -> str:
        """主入口: Plan → Gather → Distill → Generate → Evaluate → Repair"""
        # 1. 复杂度评估
        assessment = self.router.assess(modules, ccb_context)
        log.info("harness_assess", domain=domain, level=assessment.level,
                 modules=len(modules))

        # 2. 生成查询计划
        plan = self.planner.plan(domain, modules, ccb_context, assessment,
                                 domain_cache=self.domain_cache)

        # 3. Gather: 按计划执行工具查询
        facts = await self._gather(plan, modules)

        # 4. Distill: 精简上下文
        domain_summaries = self._get_related_summaries(plan.cross_domain_refs)
        distilled = facts.distill(domain_summaries=domain_summaries)

        # 5. Generate
        if assessment.generation_mode == "sectional":
            content = await self._generate_sectional(plan, facts, domain, modules)
        else:
            content = await self.agent.generate(
                module_names=modules, domain_name=domain,
                baseline_context=distilled, max_rounds=3,
            )

        # 6. Evaluate + Repair
        for round_i in range(assessment.max_repair_rounds + 1):
            eval_result = self.evaluator.evaluate(content, modules, assessment, self.llm)
            if eval_result.passed:
                break
            if round_i < assessment.max_repair_rounds:
                log.info("harness_repair", domain=domain, round=round_i+1,
                         score=eval_result.score, issues=len(eval_result.issues))
                content = await self.agent.repair(content, eval_result)

        # 7. 更新 Domain Summary Cache
        self._update_domain_cache(domain, modules, content)

        return content

    async def _gather(self, plan: GenerationPlan, modules: list[str]) -> GatheredFacts:
        """按计划执行工具查询, 不使用LLM。
        直接通过 graph_store 执行 Cypher 查询, 复用 CCB 的查询逻辑,
        而非通过 Agent 的工具层。这避免了 LLM 决策开销。"""
        facts = GatheredFacts()
        for section in plan.outline:
            for query in section.queries:
                try:
                    result = await self._execute_planned_query(query)
                    if result:
                        facts.add(section.name, query.tool_name, result)
                except Exception as e:
                    log.warning("harness_gather_error", tool=query.tool_name, error=str(e))
        return facts

    async def _execute_planned_query(self, query: "PlannedQuery") -> str | None:
        """执行单个计划查询。直接操作 graph_store, 复用 CCB 的 Cypher。"""
        # 每个 tool_name 对应一组确定性的 graph_store 查询
        # 实现细节见实施计划, 这里描述接口契约:
        # - query_module_detail → graph_store.execute_query(MODULE_DETAIL_CYPHER)
        # - query_call_chain → graph_store.execute_query(CALL_CHAIN_CYPHER)
        # - query_callers/callees → graph_store.execute_query(CALLERS_CYPHER)
        # - read_code → 读取文件 (需要 repo_path)
        # - query_implementations → graph_store.execute_query(IMPL_CYPHER)
        # - query_domain_dependencies → graph_store.execute_query(DEP_CYPHER)
        pass  # 实现细节见实施计划

    async def _generate_sectional(self, plan, facts, domain, modules) -> str:
        """分段生成: 每个 section 独立 LLM 调用。用于 complex 域。"""
        sections = []
        for section_plan in plan.outline:
            section_facts = facts.facts.get(section_plan.name, [])
            section_context = "\n".join(f.content for f in section_facts)[:3000]
            section_content = await self.agent.generate(
                module_names=modules, domain_name=domain,
                baseline_context=f"## {section_plan.name}\n{section_context}",
                max_rounds=2,
            )
            sections.append(section_content)
        combined = "\n\n".join(sections)
        # Coherence Pass: 一次轻量 LLM 调用, 统一风格和交叉引用 (~3K tokens)
        combined = await self._coherence_pass(combined, domain, modules)
        return combined

    async def _coherence_pass(self, content: str, domain: str, modules: list[str]) -> str:
        """Coherence Pass: 轻量LLM调用, 统一分段生成的内容风格和交叉引用。"""
        prompt = f"""以下是分段生成的 Wiki 页面 "{domain}"。请做以下修正:
1. 统一段落间的称谓和风格
2. 确保各段的交叉引用一致 (如段A提到的模块在段B也应保持相同描述)
3. 去除重复内容
4. 不要改变技术内容本身

{content[:8000]}"""
        messages = [{"role": "user", "content": prompt}]
        response = await self.llm.generate(messages)
        return response if len(response) > len(content) * 0.5 else content

    def _update_domain_cache(self, domain, modules, content):
        """生成完成后提取 DomainSummaryCard。"""
        # 确定性提取: 取前500字 + 模块列表
        summary = content[:500] if content else ""
        card = f"Domain: {domain}\nModules: {', '.join(modules[:10])}\nSummary: {summary}"
        self.domain_cache[domain] = card

    def _get_related_summaries(self, cross_domain_refs: list[str]) -> list[str]:
        """获取相关域的摘要卡片。"""
        return [self.domain_cache[d] for d in cross_domain_refs if d in self.domain_cache]
```

### 3.6 GuardRails (`wiki/harness_guardrails.py`)

```python
@dataclass
class GuardRailViolation:
    rule: str
    message: str
    action: str  # "warn", "block", "truncate"

class HarnessGuardRails:
    MAX_TOOL_CALLS_PER_QUERY = 15
    MAX_TOKEN_BUDGET = 50000
    MAX_OUTPUT_LENGTH = 15000
    MIN_OUTPUT_LENGTH = 500
    MAX_DUPLICATE_QUERIES = 2

    def __init__(self):
        self.query_history: list[str] = []
        self.total_tokens: int = 0

    def check_tool_call(self, tool_name: str, params: dict) -> GuardRailViolation | None:
        """检查工具调用是否违反护栏。"""
        key = f"{tool_name}:{sorted(params.items())}"
        count = self.query_history.count(key)
        if count >= self.MAX_DUPLICATE_QUERIES:
            return GuardRailViolation(
                "duplicate_query", f"Query '{tool_name}' called {count+1} times", "block"
            )
        self.query_history.append(key)
        return None

    def check_output(self, content: str) -> list[GuardRailViolation]:
        """检查输出是否违反护栏。"""
        violations = []
        if len(content) < self.MIN_OUTPUT_LENGTH:
            violations.append(GuardRailViolation(
                "too_short", f"Output {len(content)} chars < {self.MIN_OUTPUT_LENGTH}", "warn"
            ))
        if len(content) > self.MAX_OUTPUT_LENGTH:
            violations.append(GuardRailViolation(
                "too_long", f"Output {len(content)} chars > {self.MAX_OUTPUT_LENGTH}", "truncate"
            ))
        return violations
```

---

## 4. 集成点修改

### 4.1 compose.py 修改

```python
# wiki/nodes/compose.py — _compose_single_leaf_domain

# 修复 bug: 传入 repo_path 和 search_service
agent = WikiPageAgent(
    llm=llm,
    graph_store=graph_store,
    repo_path=state.get("repo_path"),           # FIX
    search_service=state.get("search_service"), # FIX
)

# 新增: Harness 路径
from wiki.harness import WikiGenerationHarness
from wiki.agent_config import HarnessConfig

harness_config = HarnessConfig.from_env()
if harness_config.enabled:
    harness = WikiGenerationHarness(agent=agent, graph_store=graph_store, llm=llm)
    content = await harness.run(domain=domain_name, modules=module_names, ccb_context=context)
else:
    # 现有路径不变
    content = await agent.generate(...)
```

### 4.2 page_agent.py 修改

```python
# 新增 repair() 方法
async def repair(self, content: str, eval_result) -> str:
    """根据 Evaluator 反馈修正内容。
    设计决策: repair 只做 LLM generate, 不带工具调用。
    它只能修复"有信息但没用好"的情况(如结构不完整、模块未提及)。
    若是信息缺失(如缺少调用链数据), 则依赖事后 heal 机制。"""
    issues_text = "\n".join(f"- [{i.category}] {i.message}" for i in eval_result.issues)
    suggestions_text = "\n".join(f"- {s}" for s in eval_result.suggestions)

    repair_prompt = f"""以下 Wiki 页面有质量问题需要修正:

## 当前问题
{issues_text}

## 修正建议
{suggestions_text}

## 当前内容
{content[:4000]}

请修正上述问题, 输出完整的修正后页面。保持原有正确内容不变, 只修复指出的问题。"""

    messages = [
        {"role": "system", "content": AGENT_GENERATE_SYSTEM},
        {"role": "user", "content": repair_prompt},
    ]
    response = await self.llm.generate(messages)
    repaired = strip_agent_artifacts(response)
    return repaired if len(repaired) > 200 else content
```

### 4.3 agent_config.py 修改

```python
@dataclass
class HarnessConfig:
    enabled: bool = False
    max_repair_rounds: int = 2
    simple_threshold: int = 5
    complex_threshold: int = 15
    llm_judge_enabled: bool = True

    @classmethod
    def from_env(cls) -> "HarnessConfig":
        return cls(
            enabled=os.getenv("WIKI__USE_HARNESS", "").lower() in ("true", "1", "yes"),
            max_repair_rounds=int(os.getenv("WIKI__HARNESS_MAX_REPAIR_ROUNDS", "2")),
            simple_threshold=int(os.getenv("WIKI__HARNESS_SIMPLE_THRESHOLD", "5")),
            complex_threshold=int(os.getenv("WIKI__HARNESS_COMPLEX_THRESHOLD", "15")),
            llm_judge_enabled=os.getenv("WIKI__HARNESS_LLM_JUDGE", "true").lower() in ("true", "1"),
        )
```

---

## 5. Domain Summary Cache (跨域记忆)

### 5.1 数据结构

```python
@dataclass
class DomainSummaryCard:
    domain_name: str
    module_names: list[str]
    entry_points: list[str]       # 主要入口模块
    responsibilities: str          # 一句话描述
    depends_on: list[str]         # 依赖的其他域
    generated_at: str             # 时间戳
    content_hash: str             # 内容 hash (增量更新用)
```

### 5.2 生命周期

1. **创建**: 每个域生成完成后, 从 content 提取 Summary Card
2. **存储**: 持久化在 pipeline state 中 (跨 compose node 保持)
3. **读取**: 后续域的 Planner 读取相关域的 Cards, 注入到 Distill 阶段
4. **更新**: 增量生成时, 比较 content_hash 判断是否需要重新生成

### 5.3 提取逻辑 (确定性)

```python
def extract_summary_card(domain: str, modules: list[str], content: str) -> DomainSummaryCard:
    """从生成的 Wiki 内容中确定性提取摘要。"""
    # 1. 取概述段的前200字作为 responsibilities
    overview_match = re.search(r"##?\s*概述\s*\n(.*?)(?=\n##|\Z)", content, re.S)
    responsibilities = (overview_match.group(1)[:200] if overview_match else "")

    # 2. 从调用链/依赖段提取跨域引用
    depends_on = re.findall(r"\[([^\]]+)\]\(", content)  # 提取 wiki links

    # 3. 入口模块 = 被外部调用最多的模块 (从 CCB 数据获取)
    entry_points = modules[:3]

    return DomainSummaryCard(
        domain_name=domain, module_names=modules,
        entry_points=entry_points, responsibilities=responsibilities,
        depends_on=depends_on, generated_at=datetime.now().isoformat(),
        content_hash=hashlib.md5(content.encode()).hexdigest(),
    )
```

---

## 6. 文件结构

| 操作 | 文件路径 | 职责 |
|------|---------|------|
| Create | `wiki/harness.py` | WikiGenerationHarness 编排器 |
| Create | `wiki/harness_planner.py` | WikiPagePlanner 查询计划 |
| Create | `wiki/harness_evaluator.py` | WikiPageEvaluator L1+L2 |
| Create | `wiki/harness_router.py` | AdaptiveRouter 复杂度评估 |
| Create | `wiki/harness_facts.py` | GatheredFacts + Distill |
| Create | `wiki/harness_guardrails.py` | GuardRails 护栏 |
| Create | `wiki/domain_summary_cache.py` | DomainSummaryCard 跨域记忆 |
| Modify | `wiki/page_agent.py` | 新增 repair() 方法 |
| Modify | `wiki/nodes/compose.py` | 集成 Harness + 修复 repo_path bug |
| Modify | `wiki/agent_config.py` | 新增 HarnessConfig |
| Create | `tests/wiki/test_harness_router.py` | Router 测试 |
| Create | `tests/wiki/test_harness_planner.py` | Planner 测试 |
| Create | `tests/wiki/test_harness_evaluator.py` | Evaluator 测试 |
| Create | `tests/wiki/test_harness_facts.py` | Facts + Distill 测试 |
| Create | `tests/wiki/test_harness_guardrails.py` | GuardRails 测试 |
| Create | `tests/wiki/test_harness_integration.py` | 集成测试 |
| Create | `tests/wiki/test_domain_summary_cache.py` | Cache 测试 |

---

## 7. 测试策略

### 7.1 单元测试 (纯确定性, 不需要 LLM/图)

- AdaptiveRouter: 各种 module_count/edge_count 组合 → 正确的 level
- WikiPagePlanner: 给定 domain/modules → 正确的查询计划
- WikiPageEvaluator.evaluate_l1: 给定 content → 正确的 score/issues
- GatheredFacts.distill: 给定原始数据 → 正确的精简结果
- GuardRails: 重复检测、长度检查
- DomainSummaryCard 提取: 给定 content → 正确的 card

### 7.2 集成测试 (Mock LLM + Mock graph)

- WikiGenerationHarness.run: 完整流程测试
- Repair loop: 验证 Evaluator 反馈 → Generator 修正
- Fallback: Harness 失败 → 降级到直接 Agent

### 7.3 不测试 (需要真实 LLM/图)

- evaluate_l2 (LLM Judge) — 需要真实 LLM
- 端到端生成质量 — 需要真实图数据

---

## 8. 风险与缓解

| 风险 | 缓解 |
|------|------|
| Planner 查询计划不够智能 | 起步保守, 后续可升级为 LLM-assisted planning |
| 确定性 Distill 丢失关键信息 | max_chars_per_section 可调, 优先保留高优先级 facts |
| 分段生成风格不一致 | Coherence Pass 统一; 先 moderate 域用 whole_page |
| Repair 循环增加延迟 | simple 域跳过 repair; 超时机制 |
| 与现有 quality_gate_node 重叠 | Harness eval 是 in-loop (快速修复), quality_gate 是 post-pipeline (最终兜底) |
| 配置项过多 | 合理默认值; 只暴露核心开关 |

---

## 9. 成功标准

| 指标 | 现有 | 目标 |
|------|------|------|
| Token 消耗/页 (moderate域) | ~41K | ≤25K |
| 模块覆盖率 (L1 检查) | 未测量 | ≥95% |
| Eval L1 首次通过率 | 未测量 | ≥80% |
| Repair 后通过率 | 未测量 | ≥95% |
| 跨域引用一致性 | 无 | DomainSummaryCard 覆盖 |
| 文件/语义工具可用 | ❌ | ✅ |
