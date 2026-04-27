# P0 — 技术债务修复设计

> 状态：已批准 2026-04-27

## 背景

Phase 0-3 实施完成后，代码审查和分析发现三项技术债务需要清理。

## 目标

消除已知技术债务，使系统进入健康状态，为后续 P1 前端补全打下基础。

---

## Task 1: Token Multiplier 传递

### 问题

`feedback_regen_token_multiplier` 和 `feedback_regen_batch_token_multiplier` 在 `config.py` 和 `feedback_loop.py` 中定义，在 `bootstrap.py` 的 `_run_feedback_wiki_regen` 中记录日志，但不传递给 `WikiService.generate()`。

### 设计

1. 在 `WikiService.generate()` 签名中添加 `token_budget_multiplier: float = 1.0`
2. 在 `_compose_all_pages` 内部，将 `core_code_budget`、`standard_code_budget`、`skeleton_code_budget` 分别乘以 `token_budget_multiplier`
3. 在 `bootstrap.py` 的 `_run_feedback_wiki_regen` 中，将 `token_multiplier` 传给 `wiki_svc.generate(..., token_budget_multiplier=token_multiplier)`
4. 移除相关 TODO 注释
5. 同步更新 `generate_stream_events()` 和 `generate_incremental()` 签名

### 影响范围

- `wiki/service.py`: generate / generate_stream_events / generate_incremental 签名
- `wiki/bootstrap.py`: _run_feedback_wiki_regen 调用
- `config.py`: 移除 docstring 中 "logged but not yet applied" 说明
- `wiki/feedback_loop.py`: 移除模块 docstring 中相关说明

---

## Task 2: MCP 表面统一

### 问题

两套 MCP 服务：主 MCP (20 工具, stdio) 和 Wiki HTTP MCP (6 工具)。命名冲突（`wiki_search` vs `search_wiki`）导致混淆。

### 设计

保留两套独立服务，各有明确定位：

| 服务 | 定位 | 工具数 |
|------|------|--------|
| 主 MCP (KnowledgeBaseMCPHandler) | stdio Agent 完整能力 | 20 (12 核心 + 8 Wiki) |
| Wiki HTTP MCP (MCPWikiServer) | 轻量 HTTP Agent 接入 | 6 |

修改内容：
1. Wiki HTTP MCP 的 `wiki_search` 与主 MCP 的 `search_wiki` 统一为 `wiki_search`（HTTP MCP 已用此名，主 MCP 侧改名为 `wiki_search`）
2. 更新 `MCP-INTEGRATION.md` 增加"两套 MCP 定位"章节
3. 主 MCP manifest 中 `search_wiki` → `wiki_search`（保持向后兼容：旧名作为别名保留一版）

### 影响范围

- `wiki/mcp_tools.py`: WIKI_MCP_TOOLS_MANIFEST 重命名
- `api/mcp_server.py`: dispatch 逻辑更新别名
- `docs/MCP-INTEGRATION.md`: 增加定位说明

---

## Task 3: 死代码清理

### 问题

`WikiSidebar.tsx` 未被引用，与 `WikiTreeNav` 功能重复。

### 设计

1. 确认 `WikiSidebar.tsx` 无引用（grep 扫描）
2. 删除文件
3. 扫描 `dashboard/src/components/wiki/` 中其他未引用导出，删除确认无用的
4. 运行前端测试确认无影响

### 影响范围

- `dashboard/src/components/wiki/WikiSidebar.tsx`: 删除
- 可能的其他死代码文件

---

## 测试计划

- [ ] Task 1: 单元测试验证 token_budget_multiplier 乘法逻辑
- [ ] Task 1: 集成测试验证 feedback → generate 路径传递
- [ ] Task 2: MCP 工具名变更后的 dispatch 测试
- [ ] Task 3: 前端测试全绿，无 import 断裂
- [ ] 全量后端 pytest 通过
- [ ] 全量前端 vitest 通过
