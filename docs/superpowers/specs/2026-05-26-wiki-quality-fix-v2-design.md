# Wiki 质量修复 v3 — Slug 命名 + DocOrchestrator 统一

**Created:** 2026-05-26
**Status:** Draft — 待审阅
**Scope:** 域 Slug 可读性改善 + DocOrchestrator 生成路径统一
**Estimated Changes:** ~300 行代码，~10 文件
**前置:** Batch 1-2 + Batch 2.5 已完成并部署

---

## 1. 背景

### 1.1 已完成的修复

| Batch | 内容 | 状态 |
|-------|------|------|
| 1 (P0) | ContentLanguage 枚举统一 + Finalize 产物清理 | ✅ |
| 2 (P1) | 后处理语言化 + Topic dedup/cap + Canonical key | ✅ |
| 2.5 (P0) | Stale 清理根因修复 + 容器域 topic 清理 + source://+CODE_REF + Compound key + TreeLinker 保护 | ✅ |

### 1.2 剩余问题

**A. Slug 可读性差**

| 问题 | 示例 | 频率 |
|------|------|------|
| `domain-NN` 匿名 slug | `domain-01`, `domain-03` | ~15% 域 |
| Hash 后缀碰撞 slug | `payment-a3f2`, `core-7b1e` | ~5% 域 |
| `unnamed` 残留 | `unnamed` | 偶发 |

**根因:** `normalize_slug` 丢弃所有 CJK 字符，中文域名 → `"unnamed"` → `domain-NN` 计数器。碰撞处理用 MD5 hash 而非语义后缀。

**B. 双生成路径**

`DomainDocAgent` 有 `generate_with_iterations()` (legacy, 默认) 和 `DocOrchestrator.generate()` (template method, 需 flag) 两条路径。Legacy 路径有 7 项能力（topic planning, timeout, guardrail 等）未迁移到 template。

---

## 2. Batch 3 — Slug 命名规范

### 2.1 核心原则

1. **不引入新依赖** — 不使用 pypinyin，从模块名（已有 ASCII）派生 slug
2. **精准修复** — 仅改 3 个断裂点，不重构整体 slug 流水线
3. **保持稳定** — DomainStabilizer 确保既有 slug 不变，仅新域受影响

### 2.2 Fix A: `_ensure_ascii_keys` 模块名派生

**文件:** `wiki/nodes/classify.py`

**当前行为:**
```python
if not ascii_slug or ascii_slug == "unnamed" or ascii_slug in result:
    unnamed_counter += 1
    ascii_slug = f"domain-{unnamed_counter:02d}"
```

**改为:**
```python
if not ascii_slug or ascii_slug == "unnamed" or ascii_slug in result:
    module_names = [name for _, name in pairs[:3]]
    candidate = normalize_slug("-".join(module_names))
    if candidate and candidate != "unnamed" and candidate not in result:
        ascii_slug = candidate
    else:
        unnamed_counter += 1
        ascii_slug = f"misc-{unnamed_counter:02d}"
```

**效果:** `domain-01` → `familypowerservice-familyrankservice`（从前 3 个模块名派生）

### 2.3 Fix B: `_dedup_parallel_naming_results` 语义后缀

**文件:** `wiki/nodes/graph_domain_decompose.py`

**当前行为:**
```python
suffix = hashlib.md5(str(result).encode()).hexdigest()[:4]
new_slug = f"{slug}-{suffix}"
```

**改为:**
```python
modules = result.get("modules", [])
if modules:
    suffix = normalize_slug("-".join(m.split(".")[-1][:12] for m in modules[:2]))
if not suffix or suffix == "unnamed":
    suffix = hashlib.md5(str(result).encode()).hexdigest()[:4]
new_slug = f"{slug}-{suffix}"
```

**效果:** `payment-a3f2` → `payment-orderservice-refundhandler`

### 2.4 Fix C: `_fallback_name` 模块名优先

**文件:** `wiki/graph_domain_namer.py`

**当前行为:** `_fallback_name(module_names)` 取第一个模块名 → normalize_slug → 可能空

**改为:** 拼接前 2-3 个模块名的短名（最后一段 `.` 分隔）

```python
@staticmethod
def _fallback_name(module_names: list[str]) -> dict[str, str]:
    short_names = [m.rsplit(".", 1)[-1] for m in (module_names or [])[:3]]
    joined = "-".join(short_names) if short_names else "unnamed"
    slug = normalize_slug(joined) or "unnamed"
    display = short_names[0] if short_names else "unnamed"
    return {"slug": slug, "display_name": display, "description": ""}
```

### 2.5 测试计划

| 测试 | 验证点 |
|------|--------|
| `test_ensure_ascii_keys_derives_from_modules` | 中文键 → 模块名 slug 而非 `domain-NN` |
| `test_ensure_ascii_keys_falls_back_to_misc` | 无模块时 → `misc-01` |
| `test_dedup_uses_semantic_suffix` | 碰撞 → 模块名后缀而非 hash |
| `test_dedup_hash_fallback` | 无模块碰撞 → 仍用 hash |
| `test_fallback_name_uses_short_modules` | 多模块 → 短名拼接 |

---

## 3. Batch 4 — DocOrchestrator 路径统一

### 3.1 核心原则

1. **渐进迁移** — 不一次性重写，逐步补齐能力
2. **不改 API** — `DocOrchestrator.generate()` 签名不变
3. **Hook 扩展** — 新增可选 hook，默认空实现，不影响 FlowDocAgent/TopicDocAgent

### 3.2 Step 1: 能力补齐

在 `DocOrchestrator` 中新增以下 hook（均有默认空实现）：

```python
class DocOrchestrator(ABC):
    # 新增 hooks
    async def plan_topics(
        self, memory: WorkingMemory, module_names: list[str],
    ) -> list[TopicPlan] | None:
        """Optional: plan topic splits before writing. Default: None (no splitting)."""
        return None

    def get_phase_timeout(self, phase: str) -> float | None:
        """Optional: per-phase timeout in seconds. Default: None (no timeout)."""
        return None

    async def run_guardrails(
        self, content: str, iteration: int, context: dict,
    ) -> GuardrailResult | None:
        """Optional: run output guardrail chain. Default: None (skip)."""
        return None

    def build_iteration_trace(self, iteration: int, quality: QualityReport) -> dict | None:
        """Optional: collect trace data. Default: None."""
        return None
```

修改 `generate()` 模板方法调用这些 hook：

```python
async def generate(self, module_names, baseline_context):
    memory = self._agent.create_memory()
    await self.pre_fill(memory, module_names)

    # NEW: topic planning
    topics = await self.plan_topics(memory, module_names)

    # Explore with optional timeout
    timeout = self.get_phase_timeout("explore")
    explore_coro = self._agent.run_tool_loop(...)
    if timeout:
        memory = await asyncio.wait_for(explore_coro, timeout)
    else:
        memory = await explore_coro

    if topics:
        # Topic-split generation path
        return await self._generate_by_topics(topics, memory, baseline_context, module_names)

    # Single-page generation path (existing)
    for iteration in range(self._max_iterations):
        timeout = self.get_phase_timeout("write")
        write_coro = self._agent.run_generation(...)
        content = await asyncio.wait_for(write_coro, timeout) if timeout else await write_coro

        content = await self._verify_code_blocks(content, memory)
        quality = await self.evaluate(content, module_names)

        # NEW: guardrails
        guardrail_result = await self.run_guardrails(content, iteration, {...})
        if guardrail_result and not guardrail_result.passed:
            # Append heal hints and continue
            ...

        # NEW: trace
        self.build_iteration_trace(iteration, quality)

        if self.is_acceptable(quality, iteration):
            break
        # re-explore...

    return self.post_process(content, module_names, memory)
```

### 3.3 Step 2: DomainDocAgent Hook 实现

`DomainDocAgent` 重写 4 个新 hook：

```python
class DomainDocAgent(DocOrchestrator):
    async def plan_topics(self, memory, module_names):
        if len(module_names) <= self._topic_split_threshold:
            return None
        return await self._plan_topics(memory, module_names)  # 既有逻辑

    def get_phase_timeout(self, phase):
        timeouts = {"explore": 180.0, "write": 120.0}
        return timeouts.get(phase)

    async def run_guardrails(self, content, iteration, context):
        return await self._output_guardrail.evaluate(content, context)

    def build_iteration_trace(self, iteration, quality):
        return {"iteration": iteration, "coverage": quality.coverage, ...}
```

### 3.4 Step 3: 翻转默认值 + 废弃

1. `core/config.py`: `use_orchestrator_template: bool = True`
2. `domain_compose.py`: 调用 `agent.generate()` 而非 `agent.generate_with_iterations()`
3. `generate_with_iterations()` 保留但仅做 `warnings.warn` + 委托到 `generate()`

### 3.5 测试计划

| 测试 | 验证点 |
|------|--------|
| `test_generate_with_topic_planning` | plan_topics 返回 topics → 走多页路径 |
| `test_generate_without_topic_planning` | plan_topics 返回 None → 走单页路径 |
| `test_phase_timeout_applied` | explore/write 有超时包装 |
| `test_guardrails_trigger_reheal` | guardrail 失败 → 重试 |
| `test_flow_doc_agent_unaffected` | FlowDocAgent 不实现新 hooks, 行为不变 |
| `test_legacy_wrapper_delegates` | `generate_with_iterations` 委托到 `generate()` |

---

## 4. 文件影响矩阵

| 文件 | Batch 3 | Batch 4 | 修改行数 |
|------|---------|---------|---------|
| `wiki/nodes/classify.py` | ✅ `_ensure_ascii_keys` | | ~15 |
| `wiki/nodes/graph_domain_decompose.py` | ✅ `_dedup_parallel_naming_results` | | ~10 |
| `wiki/graph_domain_namer.py` | ✅ `_fallback_name` | | ~10 |
| `wiki/agents/doc_orchestrator.py` | | ✅ 新 hooks + generate 扩展 | ~80 |
| `wiki/domain_doc_agent.py` | | ✅ hook 实现 + 迁移 | ~60 |
| `wiki/nodes/domain_compose.py` | | ✅ 调用路径切换 | ~10 |
| `core/config.py` | | ✅ 默认值翻转 | ~2 |
| `wiki/path_conventions.py` | (无改动) | | 0 |

**总计:** ~187 行

---

## 5. 实施顺序

```
Batch 3 (Slug): 1-2 天
  1. Fix A: _ensure_ascii_keys 模块名派生
  2. Fix B: _dedup_parallel_naming_results 语义后缀
  3. Fix C: _fallback_name 改进
  4. 测试 + 部署 + 验证 slug 命名

Batch 4 (DocOrchestrator): 2-3 天
  1. Step 1: DocOrchestrator 新增 4 个 hook + generate() 扩展
  2. Step 2: DomainDocAgent hook 实现
  3. Step 3: 翻转默认值 + 废弃 legacy
  4. 全量回归测试
```

---

## 6. 风险与回退

| 风险 | 缓解 |
|------|------|
| 模块名派生 slug 过长 | normalize_slug 截断 + 取前 3 模块 |
| 语义后缀仍碰撞 | 保留 hash 兜底 |
| DocOrchestrator 迁移引入回归 | Step 1/2 不改默认值，Step 3 翻转前全量测试 |
| FlowDocAgent/TopicDocAgent 受影响 | 新 hooks 默认空实现，无行为变化 |
| DomainStabilizer 干扰新 slug | Stabilizer 只影响增量运行，全量重新生成不受影响 |

---

## 7. 验证计划

### Batch 3 验证

```bash
# 全量重新生成后检查 slug
ssh dev "curl -s -H 'Authorization: Bearer sk-admin-test' \
  'http://127.0.0.1:8100/api/v1/wiki/ultron/domain-tree'" | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
tree = data if isinstance(data, list) else data.get('tree', [])
def check(nodes, depth=0):
    for n in nodes:
        name = n.get('name','')
        if name.startswith('domain-') or name == 'unnamed':
            print(f'  BAD: {name}')
        check(n.get('children', []), depth+1)
check(tree)
print('Expected: 0 BAD slugs')
"
```

### Batch 4 验证

```bash
# 对单域重新生成，验证 DocOrchestrator 路径
uv run pytest tests/wiki/test_domain_doc_agent.py -x -q --no-cov
# 预期: all passed, no DeprecationWarning
```

---

*本文档为 wiki 质量修复 v3 的设计 spec。实施前需经用户审阅批准。*
