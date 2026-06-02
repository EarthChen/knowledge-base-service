# Wiki 质量修复完整提案

**日期：** 2026-06-02  
**状态：** `[Sprint1-Completed]`  
**范围：** 审计报告中全部 20 个问题（6 P0 + 8 P1 + 6 P2）  
**预估工期：** 4 个 Sprint × 2-3 天 = 8-12 个工作日  
**验证方式：** 每个 Sprint 完成后在 dev 机执行 pipeline 全量重跑

---

## 一、背景与问题总结

2026-06-02 全量 pipeline 产出仅 **27 页 wiki**，**11 页被拒**。4 个完整域（含最大域 family-ecosystem 57 模块）因 agent 超时 + finalize 硬拒级联而彻底丢失。内容可信度问题（伪造代码、断链 wikilink）自上次审计延续至今。

### 当前指标 vs 目标

| 指标 | 当前 | 目标（Sprint 4 后） |
|------|------|-------------------|
| 持久化页面 | 27 | >50 |
| 被拒页面 | 11 | <3 |
| agent_error 丢域 | 4 | 0 |
| 伪造代码 | ~100% topics | <10% |
| 断链 wikilink | ~40% | <5% |
| 重复域对 | 2 | 0 |
| 死胡同域 | 39% | <10% |

---

## 二、问题覆盖矩阵

| # | 问题 | 优先级 | 归属 Sprint | 修复项 |
|---|------|--------|-------------|--------|
| 0 | 大域 agent 超时 → 整域丢失 | P0 | Sprint 1 | A0-1~A0-5 |
| 1 | Topic 页伪造 Java API | P0 | Sprint 2 | A1, A2, A3 |
| 2 | Wikilink 用标题而非路径 | P0 | Sprint 2 | A4 |
| 3 | 重复域对 (relation-rank等) | P0 | Sprint 3 | B1 |
| 4 | 跨域 topic 错放 | P0 | Sprint 3 | B3, B4 |
| 5 | Slug↔display_name 反转 | P0 | Sprint 3 | B2 |
| 6 | 模块页英文 H2 | P1 | Sprint 4 | C1 |
| 7 | 双重 H1 | P1 | Sprint 4 | C2 |
| 8 | "No nested graph children" 占位 | P1 | Sprint 4 | C3 |
| 9 | 39% 域为死胡同 | P1 | Sprint 4 | D1 |
| 10 | Intimacy 集群 5 个近似域 | P1 | Sprint 5(延后) | D2 |
| 11 | Topic 标题序号 `·专题·N` | P1 | Sprint 3 | B1/B2 附带修复 |
| 12 | 表格 GFM 间距 | P1 | Sprint 4 | C4 |
| 13 | 术语不一致 (MOA/挚友等) | P1 | Sprint 5(延后) | C5 |
| 14 | 模块页身份错配 | P2 | Sprint 2 | A2 附带修复 |
| 15 | Related Topics 重复 wikilink | P2 | Sprint 4 | C6 |
| 16 | L1 层级过多 (16→目标6-8) | P2 | Sprint 5(延后) | D3 |
| 17 | 覆盖空白 (语音房/支付) | P2 | Sprint 1 | 恢复 4 个丢失域 |
| 18 | 模块页未挂载到域 section | P2 | Sprint 4 | D4 |
| 19 | Quick L1 标签未本地化 | P2 | Sprint 4 | C1 附带修复 |

**覆盖率：** Sprint 1-4 覆盖 17/20 个问题；Sprint 5 覆盖剩余 3 个（#10, #13, #16）。

---

## 三、Sprint 1：域恢复 + LangGraph 1.2 升级（2-3 天） ✅ COMPLETED 2026-06-02

### 核心设计哲学：「不卡住就跑到成功」

```
Agent 流式输出 → idle timer 持续重置 → 无限运行直到完成
     │
     └─ 如果停止输出 3 分钟 (idle_timeout):
          触发重试 (RetryPolicy, 最多 2 次)
               │
               └─ 如果 2 次都失败:
                    error_handler → skeleton fallback → 域不会丢失
```

### 3.0 前置：升级 LangGraph

**当前版本：** `langgraph==1.1.10`  
**目标版本：** `langgraph>=1.2.0`  
**风险：低** — semver 小版本升级，零破坏性变更，所有新功能 opt-in。

```bash
uv pip install "langgraph>=1.2.0" "langgraph-checkpoint-sqlite>=3.0.0"
```

升级后获得：`TimeoutPolicy`、`error_handler`、`RetryPolicy` 组合、`NodeTimeoutError`（含丰富上下文）。

### 3.1 用 TimeoutPolicy 替代 asyncio.wait_for

**文件：** `wiki/pipeline_graph.py`、`wiki/nodes/domain_compose.py`

```python
from langgraph.graph import TimeoutPolicy, RetryPolicy

# pipeline_graph.py — compose 节点注册
graph.add_node(
    "compose_domain_agents",
    compose_domain_agents_node,
    timeout=TimeoutPolicy(
        run_timeout=3600,   # 1 小时纯安全网（正常不触发）
        idle_timeout=180,   # 3 分钟无进展 = 真正卡住
    ),
    retry_policy=RetryPolicy(max_attempts=2, retry_on=(TimeoutError,)),
    error_handler=compose_error_fallback,
)
```

```python
# domain_compose.py — 删除旧的 asyncio.wait_for 包装
# 旧: result = await asyncio.wait_for(coro, timeout=settings.wiki.domain_agent_timeout_sec)
# 新: result = await coro  # 超时由 LangGraph 节点级策略管理
```

**RAG 阶段心跳保护（检索期间无 token 输出但仍在工作）：**

```python
# 在 compose agent 的检索工具中
async def search_modules(query: str, *, runtime) -> str:
    results = await rag_search(query)
    runtime.heartbeat()  # 发出"我在工作"信号，重置 idle 计时器
    return format_results(results)
```

### 3.2 修复空错误消息

**文件：** `wiki/nodes/domain_compose.py`

```python
# _make_error_placeholder 中修改
error_msg = f"{type(error).__name__}: {str(error) or 'timeout/cancelled'}"
```

LangGraph 1.2 的 `NodeTimeoutError` 自带 `node`、`elapsed`、`kind` 属性，天然解决此问题。

### 3.3 finalize 豁免 agent_error 页面

**文件：** `wiki/nodes/finalize.py`

```python
# shell_domain_rejected 检查前增加
gen_mode = page.get("metadata", {}).get("generation_mode", "")
if is_overview and gen_mode in ("agent_error", "error_fallback"):
    # 不硬拒 — 保留带警告的骨架页
    degraded_banner = "> ⚠️ 本域文档生成失败，以下为域内模块列表，待重新生成。\n\n"
    modules_section = _extract_modules_from_error_page(page)
    updated_pages.append({
        **page, "content": degraded_banner + modules_section, "__degraded__": True
    })
    continue
```

### 3.4 增加 agent_error 的 heal 次数

**文件：** `wiki/nodes/quality_gate.py`、`core/config.py`

```python
# config.py 新增
agent_error_heal_max_cycles: int = Field(default=3, ge=1, le=5)

# quality_gate.py — 替换 `if cycles < 1:`
max_cycles = settings.wiki.agent_error_heal_max_cycles if gen_mode == "agent_error" else 1
if cycles < max_cycles:
    pages_to_heal.append(page_path)
```

### 3.5 注册 error_handler 生成 skeleton

**新文件：** `wiki/nodes/compose_error_handler.py`

```python
from langgraph.errors import NodeError
from langgraph.types import Command

async def compose_error_fallback(state: dict, *, error: NodeError) -> Command:
    """compose 节点重试耗尽后的降级处理：生成骨架页。"""
    failed_domains = _extract_failed_domains(state, error)
    skeleton_pages = []
    for domain in failed_domains:
        skeleton_pages.append({
            "path": f"/__domains__/{domain['slug']}/_overview",
            "title": domain.get("display_name", domain["slug"]),
            "page_type": "domain_overview",
            "content": _build_skeleton_content(domain),
            "metadata": {"generation_mode": "error_fallback"},
            "__degraded__": True,
        })
    return Command(
        update={"pages": state.get("pages", []) + skeleton_pages},
        goto="quality_gate",
    )
```

### Sprint 1 验证

```bash
# 1. 升级
uv pip install "langgraph>=1.2.0"

# 2. 回归测试
uv run pytest tests/wiki/ -x --timeout=300

# 3. dev 重跑
ssh dev "cd ~/review-bot/knowledge-base-service && uv pip install 'langgraph>=1.2.0' && PYTHONPATH=. .venv/bin/python -m wiki.cli run --repo ultron --full"

# 4. 验证
ssh dev "... scripts/audit_wiki_data.py --repo ultron | grep -i family"
```

**成功标准：**
- [ ] LangGraph 升级无测试失败
- [ ] family-ecosystem 出现在 wiki 输出中
- [ ] 无域静默丢失
- [ ] 错误消息非空

---

## 四、Sprint 2：内容可信度（2-3 天）

### 4.1 代码块按条件生成（A1）

**文件：** `wiki/unified_prompt_templates.py`

```python
if snippet_count >= 3:
    code_instruction = "使用以下经过验证的代码片段："
elif snippet_count > 0:
    code_instruction = "使用以下代码片段。严禁添加未列出的代码："
else:
    code_instruction = "无可用代码片段。严禁编造或虚构任何代码示例。"
```

### 4.2 接入代码验证器（A2）

**文件：** `wiki/nodes/compose.py`

在 `_sanitize_pages()` 中增加 `verify_and_inject()` 调用：
- 第一阶段：`mode="annotate"`（标注未验证代码，不删除）
- 第二阶段：验证稳定后切换为 `mode="strip"`

同时修复 #14（模块页身份错配）——验证器会检测页面引用的模块是否与标题匹配。

### 4.3 代码围栏纳入幻觉扫描（A3）

**文件：** `wiki/content_guards.py`

```python
# 旧: content_for_scan = _CODE_FENCE_RE.sub("", content)
# 新: content_for_scan = content  # 代码块也需要扫描
```

新增代码专用幻觉检查：扫描代码块中的方法/类名，标记图谱中不存在的符号。

### 4.4 Wikilink 重写为路径格式（A4）

**文件：** `wiki/nodes/finalize.py`

```python
def _rewrite_wikilinks_to_paths(content: str, title_to_path: dict[str, str]) -> str:
    """将 [[标题]] 重写为 [[/路径|标题]]"""
    def _replace(match):
        link_text = match.group(1).strip()
        if link_text.startswith("/"):
            return match.group(0)  # 已是路径格式
        path = title_to_path.get(link_text)
        if path:
            return f"[[{path}|{link_text}]]"
        return match.group(0)  # 未知标题，保持原样
    return re.sub(r"\[\[([^\]|]+)\]\]", _replace, content)
```

### Sprint 2 验证

- [ ] 抽样 10 个 topic 页：伪造代码块 < 2（从 ~3+/页降低）
- [ ] Wikilink >90% 使用 `[[/path|label]]` 格式
- [ ] `pytest tests/wiki/ -x` 通过
- [ ] 页面数量无回归

---

## 五、Sprint 3：域完整性（2-3 天）

### 5.1 树构建后全局词干合并（B1）

**文件：** `wiki/nodes/graph_domain_decompose.py`

将 `_merge_global_stem_suffix_domains()` 从 Step 6.52（子拆分前）移到树构建完成后：

```python
domain_tree = _collapse_empty_shells(_build_domain_tree(...))
# 新增：在最终树上运行词干合并
flat_slugs = _extract_leaf_slugs(domain_tree)
merged_pairs = _detect_stem_suffix_pairs(flat_slugs)
if merged_pairs:
    domain_tree = _merge_tree_nodes(domain_tree, merged_pairs)
```

解决 `relation-rank` + `relation-rank-service` 重复问题。附带修复 #11（标题序号）——合并后重复标题减少。

### 5.2 Slug↔display 验证（B2）

**文件：** `wiki/graph_domain_namer.py`

缓存命中时重新验证 slug 与 display_name 的语义一致性。拒绝不可解释的反转。

### 5.3 前缀不可链接约束强化（B3）

**文件：** `wiki/domain_semantic_clusterer.py`

```python
_BUSINESS_PREFIX_GROUPS = {
    "family": {"family", "族"},
    "intimacy": {"intimacy", "亲密", "closefriend"},
    "gift": {"gift", "礼物"},
    "quick-message": {"quick-message", "快捷消息"},
}
```

不同前缀组的模块增加 `cannot_link` 约束，防止 embedding 相似度把 family 模块拉进 intimacy 集群。

### 5.4 散布验证 → 矫正拆分（B4）

**文件：** `wiki/cluster_validation.py`、`wiki/nodes/graph_domain_decompose.py`

将现有的散布验证（当前仅日志）改为触发重新聚类，解决跨域 topic 错放问题。

### Sprint 3 验证

- [ ] `relation-rank` 系列合并为 1 个域
- [ ] `quick-message` 系列合并为 1 个域
- [ ] Family 模块聚类到 family 前缀域下
- [ ] `pytest tests/wiki/test_decompose*.py -x` 通过

---

## 六、Sprint 4：打磨与结构优化（3-4 天）

### 6.1 格式化修复包（C1-C4, C6）

| 项 | 修改 | 文件 |
|----|------|------|
| C1 | 中文 H2 模板（替代英文）+ 修复 #19 Quick 标签 | `composer.py` |
| C2 | 不生成模板 H1；strip 所有匹配标题的 body H1 | `composer.py`, `finalize.py` |
| C3 | children 为空时省略"No nested graph children" | `composer.py` |
| C4 | 表格前确保 `\n\n` | `finalize.py` |
| C6 | Related Topics 中 wikilink 去重 | `finalize.py` |

### 6.2 空域合并（D1）

**文件：** `wiki/nodes/graph_domain_decompose.py`、`core/config.py`

- `domain_budget_max` 从 20 降至 16
- 树构建后清理无模块+无内容的空壳域
- 目标：死胡同域 < 10%（从 39% 降低）

### 6.3 模块页挂载到域 section（D4）

**文件：** `wiki/nodes/domain_compose.py`

确保模块页作为子节点链接到所属域的 section。

### Sprint 4 验证

- [ ] 模块页使用中文 H2 标题
- [ ] 无双重 H1
- [ ] 表格渲染正确
- [ ] 死胡同域 < 10%
- [ ] 前端导航完整

---

## 七、Sprint 5：延后项（5+ 天，按需启动）

| 项 | 说明 | 延后原因 |
|----|------|----------|
| A0-6 | 大域分批生成（Accumulator 模式） | Sprint 1 的 idle_timeout + error_handler 已覆盖大部分场景 |
| C5 | 术语表强制统一（#13） | 需新建子系统（术语字典+验证规则） |
| D2 | Intimacy 集群合并 5→2（#10） | 依赖 Sprint 3 B3 完成后评估 |
| D3 | L1 层级重构 16→6-8（#16） | 最大范围改动，需产品决策目标结构 |

---

## 八、风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| LangGraph 1.2 升级引发回归 | 低 | 高 | 全量测试套件验证；semver 小版本保证无破坏 |
| A0-3 豁免掩盖未来失败 | 中 | 中 | degraded 页面计数监控 + 告警（>2 页/次即告警） |
| A2 验证器误删合法代码 | 低 | 高 | 第一阶段仅标注不删除，验证后再升级 |
| B1 词干合并误合并不同域 | 低 | 高 | 要求 >50% 模块重叠才允许合并 |
| 多 Sprint 修改 finalize.py 冲突 | 中 | 低 | 各 Sprint 修改不同代码段；顺序提交 |

---

## 九、验证计划

### 单元测试（每 Sprint）

| Sprint | 新增测试 |
|--------|----------|
| 1 | `test_compose_timeout_policy`, `test_error_placeholder_message`, `test_finalize_agent_error_exempt`, `test_heal_cycles_3` |
| 2 | `test_conditional_code_prompt`, `test_verify_and_inject`, `test_code_fence_scan`, `test_wikilink_rewrite` |
| 3 | `test_post_tree_stem_merge`, `test_slug_display_validation`, `test_prefix_cannot_link`, `test_scatter_split` |
| 4 | `test_chinese_h2`, `test_strip_double_h1`, `test_table_spacing`, `test_wikilink_dedup`, `test_empty_domain_prune` |

### 集成验证

每 Sprint 后在 dev 执行：
```bash
uv run pytest tests/wiki/ -x --timeout=300
ssh dev "... -m wiki.cli run --repo ultron --full"
ssh dev "... scripts/audit_wiki_data.py --repo ultron --output data/wiki-audit-post-sprint-N.json"
```

对比 baseline：页面数、rejected 数、域覆盖率。

---

## 十、审批清单

- [ ] Sprint 序列和优先级确认
- [ ] LangGraph 1.2 升级方案认可（idle_timeout + error_handler）
- [ ] 「不卡住就跑到成功」设计哲学确认
- [ ] 降级页面方案（skeleton + banner）对用户可接受
- [ ] 配置变更可接受（heal 次数、idle_timeout 参数）
- [ ] 延后项安排合理

**批准后：** 立即启动 Sprint 1 实施。
