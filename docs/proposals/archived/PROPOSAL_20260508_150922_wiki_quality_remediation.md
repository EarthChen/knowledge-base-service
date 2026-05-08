# 提案: Wiki 页面质量修复 — Agent 泄漏、CONTEXT_GAP 残留与反幻觉增强

**状态**: AwaitingApproval  
**创建时间**: 2026-05-08 15:09:22  
**关联文件**: page_agent.py, nodes/compose.py, unified_prompt_templates.py, quality_evaluator.py, sanitize

---

## 背景

### 质量扫描结果（22 个 topic 页面）

| 问题类型 | 影响页面数 | 占比 | 严重程度 |
|----------|-----------|------|---------|
| Agent 推理文本泄漏 (THINKING_LEAK) | 4 | 18% | **P0** — 用户可见的 LLM 内部思考 |
| 未解析的 CONTEXT_GAP 标记 | 13 | 59% | **P1** — HTML 注释暴露给用户 |
| 缺失调用链/流程图 (NO_CALL_CHAIN) | 10 | 45% | P2 — 信息不完整但不误导 |
| 虚构内容 (FAKE_SOURCE/hallucination) | 1+ | ~5% | **P0** — 误导性信息 |
| 低置信度 (<0.5) | 4 | 18% | P2 — 质量标记但不可见 |

**22 个 topic 页面全部存在至少一个质量问题。**

### 受影响页面清单

| 页面 | 问题 |
|------|------|
| ClosedFriendSendGiftOrderHandler-group | THINKING_LEAK, CONTEXT_GAP(1) |
| ClosedFriendRemoteServiceImpl-group | NO_CALL_CHAIN |
| 关系榜单服务 | THINKING_LEAK, FAKE_SOURCE |
| 行为统计处理 | NO_CALL_CHAIN, LOW_CONF(0.45) |
| 用户亲密度关系服务 | CONTEXT_GAP(3) |
| 直播快速互动 | CONTEXT_GAP(1), LOW_CONF(0.45) |
| 互动印记与亲密度统计 | CONTEXT_GAP(1), NO_CALL_CHAIN |
| 直播互动服务 | LOW_CONF(0.45) |
| 亲密度配置与数据支持 | CONTEXT_GAP(1), NO_CALL_CHAIN |
| UserConversationMoaServiceImpl-group | CONTEXT_GAP(3), NO_CALL_CHAIN |
| ClosedFriendReleaseRecordService-group | CONTEXT_GAP(1), NO_CALL_CHAIN |
| ClosedFriendConfigProvider-group | CONTEXT_GAP(1) |
| UserIntimacyService-group | CONTEXT_GAP(1), NO_CALL_CHAIN |
| UserRelationRemoteServiceImpl-group | CONTEXT_GAP(1), NO_CALL_CHAIN |
| MdpUserMoaWrapperService-group | THINKING_LEAK |
| UserCommonRemoteServiceImpl-group | CONTEXT_GAP(1), NO_CALL_CHAIN |
| 用户VIP服务 | CONTEXT_GAP(1) |
| 用户等级规则与配置 | CONTEXT_GAP(1) |
| 用户等级与成长服务 | THINKING_LEAK |
| UserProfileRemoteServiceImpl-group | NO_CALL_CHAIN |
| UserVipRemoteServiceImpl-group | LOW_CONF(0.0) |

---

## 根因分析

### 问题 1: Agent 推理文本泄漏（4 页，P0）

**根因**: `wiki/page_agent.py:538-540`

```python
if not tool_calls:
    if text_content:
        return str(text_content)  # 无条件将 LLM 输出当终稿
```

当 LLM 未使用 function calling 而是在 `content` 中以纯文本输出推理 + tool call JSON 时，`enrich()` 将整段内容当作"最终 Wiki 页面"返回。

**调用链**: `compose_leaf_pages_node` → `_enrich_pages_with_agent` → `WikiPageAgent.enrich()` → 无条件写回 `page_dict["content"]`

### 问题 2: CONTEXT_GAP 残留（13 页，P1）

**根因**: 双重失败

1. **生成阶段**: `unified_prompt_templates.py` 指示 LLM 在上下文不足时标记 `<!-- CONTEXT_GAP: ... -->`，这是正确行为。
2. **Agent 阶段**: `WikiPageAgent.enrich()` 本应解析并补充这些 gap，但部分 gap 无法通过 tools 解决时，按设计保留标记——然而这些标记应在最终发布前被清除或转为用户友好文案。
3. **后处理阶段**: `sanitize_wiki_content` 不清理 CONTEXT_GAP 标记，也没有"发布前最终清洗"步骤。

### 问题 3: 虚构内容（关系榜单服务等，P0）

**根因**: 多因素叠加

| 因素 | 详情 |
|------|------|
| 指令张力 | prompt 要求固定章节（sequenceDiagram、核心服务详解），上下文不足时 LLM 倾向"填满" |
| 摘要阶段反幻觉弱 | `_LEAF_MODULE_SUMMARY_PROMPT` 的反幻觉约束弱于 `UNIFIED` 级别 |
| 图表无溯源约束 | `SemanticDiagramGenerator` 未要求参与者来自实体列表 |
| truthfulness 写死 1.0 | `quality_evaluator.py` 中 `structural_check` 的 truthfulness 固定为 1.0 |
| 反幻觉 Layer 2-3 未实施 | 机械引用注入 + 生成后事实核查仍为"待开发" |

### 问题 4: 缺失调用链（10 页，P2）

**根因**: 图数据库中部分模块的调用链数据为空，prompt 正确处理为"当前上下文中未提供调用链数据，不生成流程图"。这不是 bug，而是索引覆盖度问题。

### 问题 5: RPC 服务入口页面内容过浅（P1）

**典型页面**: `UserProfileRemoteServiceImpl-group`、`UserVipRemoteServiceImpl-group` 等

**现象**: 这些 RPC facade 类的 wiki 页面只描述了方法签名和直接的委托调用（如 `basicUserProfileDomainRepoV2.queryUserTagsName(uid)`），没有深入到：
- 底层 domain repo 的具体业务逻辑
- 数据库操作和数据模型
- 跨服务调用链和业务上下文
- 方法间的关联和业务场景

**根因**: 
1. **上下文截断**: `ContentContextBuilder` 构建上下文时，对 facade 类只提取了直接的方法签名和一级依赖，未递归追踪到 domain repo 层的实现
2. **模块粒度**: 索引和分组以单个类为粒度，facade 类本身逻辑确实很薄（只做委托），真正的业务逻辑在 domain repo 中
3. **Prompt 侧**: prompt 要求"仅描述下方实体与方法中列出的服务/类"，当上下文只包含 facade 方法时，LLM 能写的内容有限

---

## 目标

1. **P0 — 消除 Agent 推理泄漏**: 任何情况下 WikiPageAgent 输出不得包含 LLM 内部推理文本
2. **P0 — 消除虚构内容**: 图表和正文中的实体/服务/调用方必须可溯源
3. **P1 — 清理 CONTEXT_GAP 残留**: 发布页面中不应包含原始 `<!-- CONTEXT_GAP -->` 标记
4. **P1 — 增强 RPC 入口页面深度**: facade 类页面应包含底层实现的关键逻辑
5. **P2 — 提升质量门有效性**: truthfulness 不应写死 1.0

---

## 设计方案

### Fix 1: Agent 输出清洗（P0，修复推理泄漏）

**文件**: `wiki/page_agent.py`

在 `enrich()` 返回前增加输出清洗:

1. **检测推理前缀**: 若 `text_content` 以常见推理模式开头（"我需要"、"让我"、"从工作记忆"等），截取第一个 `## ` 标题之后的内容
2. **剥离文内 tool JSON**: 正则移除 ` ```json { "tools": [...] } ``` ` 代码块
3. **回退策略**: 若清洗后内容为空或过短，保留原始页面内容（不应用 Agent 结果）
4. **日志告警**: 检测到推理泄漏时记 `WARNING` 级别日志

**预估改动**: ~30 行新增代码

### Fix 2: CONTEXT_GAP 发布前清洗（P1）

**文件**: `wiki/nodes/compose.py` 中的 `_sanitize_pages` 或新增后处理步骤

1. 将残留的 `<!-- CONTEXT_GAP: xxx -->` 替换为用户友好文案: `> ℹ️ 此处信息待补充: xxx`
2. 或直接移除 CONTEXT_GAP 标记（较激进）

**预估改动**: ~10 行新增代码

### Fix 3: 图表反幻觉约束（P0，修复虚构内容）

**文件**: `wiki/unified_prompt_templates.py` 或 diagram 生成处

1. `SemanticDiagramGenerator` 的 system prompt 增加: "参与者名称**必须**来自给定的实体/调用链列表，禁止新增未出现的服务名"
2. `_LEAF_MODULE_SUMMARY_PROMPT` 对齐 UNIFIED 级别的反幻觉约束

**预估改动**: ~20 行 prompt 修改

### Fix 4: RPC 入口页面内容增强（P1）

**方案**: 在 `ContentContextBuilder.build_context` 中，当检测到目标实体是 RPC 入口类时，自动追踪其一级依赖（domain repo）的关键方法实现，将这些上下文一并注入 prompt。

**RPC 入口识别策略**（按优先级）:

1. **首选 — 图查询 `@MoaProvider` 注解**: 图数据库 `Class` 节点已有 `annotations` 字段，`GraphEnricher.enrich_scan_rpc_provider_classes()` 已标记所有 `@MoaProvider` / `@DubboService` 类。`ContentContextBuilder` 可通过 `annotations` 属性直接判断：
   ```python
   is_rpc_entry = any(
       "MoaProvider" in ann or "DubboService" in ann
       for ann in (entity.annotations or [])
   )
   ```
2. **备选 — LLM 推断**: 若注解信息不完整（如某些类未索引注解），可在 compose 阶段让 LLM 根据代码结构推断（方法体仅为单行委托调用 + 类实现了 Remote 接口），但这增加 LLM 调用开销，作为降级方案。

**文件**: `wiki/content_context_builder.py`（或等价的上下文构建模块）

1. 识别 RPC 入口: 从图查询 `Class` 节点的 `annotations` 属性中检查 `@MoaProvider` / `@DubboService`
2. 对 RPC 入口的每个方法，通过图的 `CALLS` 边追踪到 domain repo 方法，提取该方法的 `code_snippet`（限制长度）
3. 将追踪到的上下文以"底层实现详情"section 注入 prompt context

**预估改动**: ~50-80 行，取决于图查询支持度

### Fix 5: 质量门增强（P2）

**文件**: `wiki/quality_evaluator.py`

1. `structural_check` 中 truthfulness 不再固定 1.0
2. 检测到 THINKING_LEAK 或 FAKE_SOURCE 模式时降低 truthfulness 分数
3. 可选: 页面发布前运行 `llm_judge_evaluate` 作为可选门控

**预估改动**: ~15 行修改

---

## 修改文件清单

| 文件 | 变更内容 | 优先级 |
|------|---------|--------|
| `wiki/page_agent.py` | `enrich()` 返回前增加输出清洗 + 回退逻辑 | P0 |
| `wiki/nodes/compose.py` | `_sanitize_pages` 增加 CONTEXT_GAP 清洗 | P1 |
| `wiki/unified_prompt_templates.py` | `_LEAF_MODULE_SUMMARY_PROMPT` 加强反幻觉 | P0 |
| `wiki/content_context_builder.py` | facade 类自动追踪 domain repo 上下文 | P1 |
| `wiki/quality_evaluator.py` | truthfulness 动态计算，检测已知质量模式 | P2 |

---

## 执行顺序

1. **Batch 1 (P0)**: page_agent.py 输出清洗 + unified_prompt_templates.py 反幻觉加强
2. **Batch 2 (P1)**: compose.py CONTEXT_GAP 发布清洗 + content_context_builder facade 追踪增强
3. **Batch 3 (P2)**: quality_evaluator.py 动态 truthfulness
4. **验证**: 重新生成 wiki 并运行质量扫描

---

## 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| 清洗正则误伤正常内容 | 仅匹配明确模式（"我需要"开头 + tool JSON 块），保守策略 |
| CONTEXT_GAP 清洗掩盖真实缺失 | 转为用户可见提示而非静默删除 |
| prompt 修改影响已有高质量页面 | 约束仅新增"禁止"规则，不改变已有正确行为 |

---

## 成功标准

- [ ] 重新生成后 0 个页面包含 Agent 推理文本
- [ ] 重新生成后 0 个页面包含原始 `<!-- CONTEXT_GAP -->` 标记
- [ ] 关系榜单服务等页面不再包含虚构组件/调用方
- [ ] quality_evaluator truthfulness 能反映实际质量
