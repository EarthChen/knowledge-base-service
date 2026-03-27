# 知识库服务融入开发流程设计 (KB Dev Workflow Integration)

**状态**: Approved
**日期**: 2026-03-27
**作者**: AI Agent (brainstorming session)

---

## 1. 背景与目标

### 1.1 背景

knowledge-base-service 是一个独立的 RAG 服务，已具备完整的代码/文档索引、语义搜索、图查询、MCP 工具接口和多业务隔离能力。当前需要将其融入公司内部业务项目（以 ultron 系列服务为主）的日常开发和文档维护流程中，以系统性地解决以下痛点：

1. **代码理解困难**（P0）— 项目庞大、跨服务调用链复杂，理解代码耗时长
2. **文档缺失/过时**（P1）— 文档跟不上代码变更，描述与实际代码不一致
3. **AI Agent 幻觉**（P2）— AI 工具生成不存在的 API 或错误的方法签名
4. **开发效率**（P3）— 希望 AI Agent 在编码时自动查询知识库获取真实上下文

### 1.2 目标

采用**渐进三阶段方案**，将知识库服务从"被动工具"转变为"开发流程基础设施"：

| 阶段 | 目标 | 解决痛点 |
|------|------|---------|
| Phase 1 | 开发者即时接入 | P0 代码理解 + P2 AI 幻觉 |
| Phase 2 | 文档自维护体系 | P1 文档缺失/过时 |
| Phase 3 | CI/CD 全闭环 | P3 开发效率 |

### 1.3 验收标准

| Phase | 验收指标 | 衡量方式 |
|-------|---------|---------|
| 1 | 开发者首次 KB 查询可在 5 分钟内完成配置 | 接入指南 walkthrough |
| 1 | Agent 编写跨服务代码时，API 签名准确率显著提升 | 对比 KB 查询前后的代码 Review 反馈 |
| 2 | `kb-doc-writer` Skill 可在 Cursor 中成功激活并完成文档编写 | 端到端测试 |
| 2 | 文档审计可检出过时引用 | 对已知过时文档执行审计 |
| 3 | PR 合并后 5 分钟内 KB 索引自动更新 | CI job 监控 |
| 3 | Review Bot Review 时可调用 KB 查询跨服务影响 | E2E Review 测试 |

### 1.4 非目标

- 不改变 knowledge-base-service 的核心架构
- 不替代 code-review-bot 已有的文档维护功能
- 不引入新的外部第三方 SaaS 服务（可使用现有 GitLab、ACP Gateway 等内部基础设施）

---

## 2. 整体架构

### 2.1 三层模型

```
ultron 各业务服务（维护自身文档）
        ↓ 索引代码+文档
knowledge-base-service（中央知识库）
        ↓ 提供 RAG 上下文
   ┌────┴────┐
   │         │
Cursor/Agent  code-review-bot → ACP Gateway → Agent + KB
(日常开发)     (PR 触发 Review)
```

| 层 | 职责 | 归属 |
|---|---|---|
| **知识库层** | 代码/文档索引、存储、检索。维护接入指南和模板 | `agent-work/knowledge-base-service` |
| **业务层** | 自维护 `docs/`、配置 Cursor Rules、CI 钩子 | 各 ultron 服务仓库 |
| **消费层** | 通过 MCP/HTTP 查询知识库、生成代码、Review | Cursor / code-review-bot |

### 2.2 核心原则

1. **知识库只做"存储和检索"** — 不关心业务逻辑
2. **各业务服务自维护文档** — 文档跟代码放在一起
3. **Agent 通过 Cursor Rules 自动查询** — 零改变开发习惯
4. **CI 管道驱动索引同步** — 保证知识库始终最新

### 2.3 Rules + Skills 双轨策略

| 交付物 | 形式 | 理由 |
|--------|------|------|
| 编码时查询 KB | **Rule** | 轻量护栏，每次写代码自动生效，防止 AI 幻觉 |
| 文档编写工作流 | **Skill** | 复杂多步骤流程，按需激活 |
| 文档审计工作流 | **Skill** | 定期执行的复杂任务 |
| 新服务接入 KB | **Skill** | 一次性 Onboarding 流程 |

Rule 简短精炼不消耗过多 token；Skill 承载复杂逻辑只在需要时激活。Rule 放在各项目仓库（项目级），Skill 可全局共享（`~/.cursor/skills/`）。

---

## 3. Phase 1：开发者即时接入

**目标**：让开发者在 Cursor 中写代码时，Agent 自动查询知识库获取真实上下文。
**预计周期**：1-2 天

### 3.1 前置：业务服务索引

**索引策略**：同一 business + 不同 repository（支持跨服务搜索，这是解决"代码理解困难"的关键）。

每个 ultron 服务对应一个 `repository`（如 `ultron-api`、`ultron-room`），所有 repository 在同一个 business 下，支持跨服务语义搜索和图查询。

**批量索引脚本** `scripts/index-services.sh`：

```bash
#!/bin/bash
BASE="/path/to/ultron-services"
KB_URL="http://kb-service:8100/api/v1/index"
KB_TOKEN="sk-admin-xxx"

SERVICES=(ultron-activity ultron-api ultron-basic ultron-room ...)

for svc in "${SERVICES[@]}"; do
  echo "Indexing $svc..."
  curl -s -X POST "$KB_URL" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $KB_TOKEN" \
    -d "{\"directory\": \"$BASE/$svc\", \"mode\": \"full\", \"repository\": \"$svc\"}"
done

# 索引统一文档仓库
curl -s -X POST "$KB_URL" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KB_TOKEN" \
  -d "{\"directory\": \"$BASE/ultron-doc\", \"mode\": \"full\", \"repository\": \"ultron-doc\"}"
```

### 3.2 Cursor Rule 模板：编码时查询 KB

文件：`docs/templates/knowledge-base-coding.mdc`

核心规则（alwaysApply: true，匹配 `**/*.java`, `**/*.py`, `**/*.go`, `**/*.ts`）：

1. **禁止臆造 API** — 不确定类/方法签名时，必须先用 `rag_query` 或 `rag_graph(find_entity)` 确认
2. **跨服务调用前查询** — 涉及 RPC/HTTP/MQ 跨服务交互时，先用 `rag_query` 搜索目标服务接口定义
3. **继承/实现接口前查询** — 用 `rag_graph(inheritance_tree / class_methods)` 确认父类/接口完整签名
4. **修改公共方法前查调用链** — 用 `rag_graph(call_chain, upstream)` 了解哪些调用方受影响

查询策略优先级：FQN 精确搜索 > 关键词搜索 > 语义搜索 > 图查询

### 3.3 MCP 配置模板

文件：`docs/templates/mcp-config.json`

```json
{
  "mcpServers": {
    "knowledge-base": {
      "url": "http://localhost:8100/api/v1/mcp",
      "headers": {
        "Authorization": "Bearer <your-api-token>"
      }
    }
  }
}
```

Token 绑定了 business 时无需 `X-Business-Id`。

### 3.4 业务项目接入指南

文件：`docs/ONBOARDING.md`

内容结构：

1. **前置条件** — 知识库服务地址、Token 申请流程
2. **索引你的仓库** — 一键索引脚本 + Dashboard 验证
3. **配置 Cursor MCP** — 复制 `mcp-config.json` 到项目 `.cursor/`
4. **安装 Cursor Rules** — 复制 `knowledge-base-coding.mdc` 到 `.cursor/rules/`
5. **验证接入成功** — 测试搜索命令示例
6. **最佳实践** — 常见场景 Prompt 示例

### 3.5 Phase 1 交付物清单

| 交付物 | 路径 | 说明 |
|--------|------|------|
| 索引脚本 | `scripts/index-services.sh` | 批量索引 ultron 服务 |
| Cursor Rule (编码) | `docs/templates/knowledge-base-coding.mdc` | 编码时自动查询 KB |
| MCP 配置模板 | `docs/templates/mcp-config.json` | Cursor MCP 配置 |
| 接入指南 | `docs/ONBOARDING.md` | 业务项目接入步骤 |

---

## 4. Phase 2：文档自维护体系

**目标**：建立基于知识库的文档编写和审计工作流，保障文档与代码的一致性。
**预计周期**：3-5 天

### 4.1 文档目录规范

采用 code-review-bot `doc-maintenance` Skill 中已定义的标准结构（8 维度 + 规模自适应拆分），不重复定义。关键维度：

| 优先级 | 文档 | 说明 |
|--------|------|------|
| P0 | README.md | 项目概览 |
| P1 | docs/api.md 或 docs/api/ | API/RPC 接口（按规模拆分） |
| P2 | docs/database.md | 数据库设计 |
| P3 | docs/architecture.md | 服务架构 |
| P4 | docs/business-flows.md 或 docs/flows/ | 业务流程（按规模拆分） |
| P5 | docs/configuration.md 或 docs/config/ | 配置说明（按规模拆分） |

### 4.2 kb-doc-writer Skill

全局 Skill（`~/.cursor/skills/kb-doc-writer/SKILL.md`），供开发者在 Cursor 中手动激活。

**工作流**：

1. **查询 KB 获取服务全貌** — `rag_graph(graph_stats)` 查看索引统计
2. **获取接口列表** — `rag_graph(file_entities)` / `rag_graph(class_methods)` 列出 API 接口
3. **获取调用关系** — `rag_graph(call_chain)` / `rag_graph(inheritance_tree)` 追踪调用链
4. **搜索已有文档** — `rag_query("服务名 文档")` 避免重复编写
5. **生成/更新文档** — 基于查询结果编写，遵循 code-review-bot 定义的文档规范
6. **交叉验证** — 文档中每个类名/方法名用 `rag_query` 确认在代码中真实存在
7. **增量索引** — `rag_index(mode=incremental)` 将新文档索引到知识库

**与 code-review-bot 的分工**：
- `code-review-bot/doc-maintenance` — PR 触发的自动文档维护（Review Bot 执行）
- `kb-doc-writer` — 开发者主动触发的文档编写（开发者在 Cursor 中执行），增加 KB 验证层

### 4.3 kb-doc-auditor Skill

全局 Skill（`~/.cursor/skills/kb-doc-auditor/SKILL.md`），定期或按需执行文档准确性审计。

**工作流**：

1. 遍历目标 `docs/` 下所有 `.md` 文件
2. 提取文档中提到的类名、方法名、接口名
3. 对每个名称用 `rag_query` / `rag_graph(find_entity)` 验证在代码中是否存在
4. 标记结果：
   - `[🚫 已删除/重命名]` — 代码中不存在
   - `[⚠️ 签名已变更]` — 存在但签名不匹配
   - `[✅ 准确]` — 存在且一致
5. 生成审计报告

### 4.4 变更驱动的文档更新

当代码变更后，开发者可通过 `kb-doc-writer` Skill 的增量模式执行：

1. 获取变更的类/方法列表（`git diff`）
2. 用 `rag_query` 搜索提及这些实体的已有文档
3. 对比文档描述与最新代码
4. 自动生成更新建议或直接更新

### 4.5 Cursor Rule 模板：文档维护时查询 KB

文件：`docs/templates/knowledge-base-docs.mdc`

核心规则（alwaysApply: true，匹配 `**/*.md`, `**/*.rst`）：

1. **文档中所有代码引用必须来自 KB 查询结果** — 写类名、方法签名前，先用 `rag_query` 或 `rag_graph(find_entity)` 确认真实定义
2. **写文档前先搜索已有文档** — 用 `rag_query("目标功能关键词")` 检查是否已有相关文档，避免重复
3. **调用链和依赖关系使用图查询获取** — 不凭直觉画流程图，用 `rag_graph(call_chain)` 获取真实调用链
4. **编写完成后验证 + 索引** — 用 `rag_query` 验证引用存在，完成后用 `rag_index(mode=incremental)` 入库

与编码 Rule 的区别：编码 Rule 面向 `*.java/*.py` 等代码文件，防止 AI 幻觉；文档 Rule 面向 `*.md/*.rst`，保障文档内容的准确性。两者互补。

### 4.6 Phase 2 交付物清单

| 交付物 | 形式 | 路径 |
|--------|------|------|
| 文档编写 Skill | Skill | `~/.cursor/skills/kb-doc-writer/SKILL.md` |
| 文档审计 Skill | Skill | `~/.cursor/skills/kb-doc-auditor/SKILL.md` |
| Cursor Rule (文档) | Rule | `docs/templates/knowledge-base-docs.mdc` |

---

## 5. Phase 3：CI/CD 全闭环

**目标**：将知识库完全融入 CI/CD 管线，实现无感知的知识同步，同时强化 Phase 1（代码理解）和 Phase 2（文档准确性）的效果。
**预计周期**：5-7 天（模板与文档），首次全量落地（索引所有 ultron 服务 + E2E 测试）需额外 2-3 天

### 5.0 前提条件与依赖 API

| 依赖项 | 状态 | 说明 |
|--------|------|------|
| `POST /api/v1/index/files` | ✅ 已实现 | 直接传入文件内容索引 |
| `POST /api/v1/index` (incremental) | ✅ 已实现 | git diff 增量索引 |
| `POST /api/v1/sync/all` | ✅ 已实现 | 批量同步所有仓库 |
| `scripts/ci-index.py` | 待实现 | CI 调用的封装脚本 |
| ACP Gateway MCP 配置注入 | 待验证 | Gateway 已有 RAG 代理，需验证 MCP 工具注入 |
| GitLab CI runner 网络可达 KB 服务 | 待确认 | CI 机器需要能访问 KB API |

### 5.1 自动增量索引

**两种集成方式**：

| 方式 | 适用场景 | 说明 |
|------|---------|------|
| GitLab Webhook → ACP Gateway → KB | 已部署 Gateway | 在 GitLab 配置 Webhook |
| CI Pipeline 直接调用 KB API | 无 Gateway | `.gitlab-ci.yml` 添加 post-merge job |

**CI Pipeline 方案**（推荐）：

在各 ultron 服务的 `.gitlab-ci.yml` 中添加 post-merge job，合并到主分支后自动触发增量索引。

知识库服务提供 `scripts/ci-index.py` 脚本供 CI 调用：
- 通过 `git diff --name-only HEAD~1 HEAD` 获取变更文件
- 调用 `POST /api/v1/index/files` 传入文件内容（无需 CI 机器访问代码目录）
- 支持代码文件和文档文件（`.md`, `.rst`, `.txt`）

### 5.2 Review Bot + 知识库联动

在 code-review-bot 的 Review 流程中增加 KB 查询步骤：

1. **Review 上下文增强** — Agent 在 Review 时通过 `rag_query` 获取变更涉及的跨服务接口定义
2. **影响范围分析** — 当 MR 修改了公共方法，自动查询 `rag_graph(call_chain, upstream)` 检查上游调用方
3. **文档维护辅助** — doc-maintenance Skill 在编写文档时，通过 `rag_query` 验证引用的准确性

**集成方式**：在 ACP Gateway 的 MCP 配置中注入 knowledge-base MCP server，让 Review Agent 可直接调用 `rag_query` / `rag_graph`。

### 5.3 定期文档审计

- 每月（或按需）由 Agent 执行 `kb-doc-auditor` Skill
- 遍历统一文档仓库 `ultron-doc` 的所有文档
- 通过 KB 验证每个代码引用的准确性
- 生成审计报告，标注过时/缺失/不一致的内容

### 5.4 知识库新鲜度保障策略

| 策略 | 触发方式 | 覆盖范围 |
|------|---------|---------|
| PR 合并增量索引 | CI post-merge job | 代码+文档变更文件 |
| Dashboard Sync All | 手动/定时 | 所有已索引仓库 |
| 全量重建 | 按需 | 所有文件（模型切换/数据异常时） |
| 文档审计 | 每月/手动 | 文档准确性验证 |

### 5.5 Phase 3 交付物清单

| 交付物 | 路径 | 说明 |
|--------|------|------|
| CI 索引脚本 | `scripts/ci-index.py` | GitLab CI 调用的增量索引脚本 |
| CI 配置模板 | `docs/templates/gitlab-ci-kb.yml` | `.gitlab-ci.yml` 片段 |
| ACP Gateway KB MCP 配置 | ACP Gateway 配置 | 让 Review Agent 可查询 KB |

---

## 6. 完整交付物汇总

| Phase | 交付物 | 形式 | 受众 | 路径 |
|-------|--------|------|------|------|
| 1 | Cursor Rule (编码查询 KB) | Rule | 开发者 | `docs/templates/knowledge-base-coding.mdc` |
| 1 | MCP 配置模板 | 配置文件 | 开发者 | `docs/templates/mcp-config.json` |
| 1 | 业务接入指南 | 文档 | 开发者/团队 | `docs/ONBOARDING.md` |
| 1 | 批量索引脚本 | 脚本 | 运维/管理 | `scripts/index-services.sh` |
| 2 | kb-doc-writer Skill | Skill | 开发者 | `~/.cursor/skills/kb-doc-writer/SKILL.md` |
| 2 | kb-doc-auditor Skill | Skill | 开发者/管理 | `~/.cursor/skills/kb-doc-auditor/SKILL.md` |
| 2 | Cursor Rule (文档查询 KB) | Rule | 开发者 | `docs/templates/knowledge-base-docs.mdc` |
| 3 | CI 索引脚本 | 脚本 | DevOps | `scripts/ci-index.py` |
| 3 | CI 配置模板 | 配置 | DevOps | `docs/templates/gitlab-ci-kb.yml` |
| 3 | ACP Gateway KB MCP 配置 | 配置 | Review Bot | ACP Gateway 配置 |

---

## 7. 跨系统依赖与责任方

| 系统 | 责任方 | 本方案涉及的变更 |
|------|--------|----------------|
| knowledge-base-service | KB 团队（当前项目） | 提供模板、脚本、文档 |
| 各 ultron 服务仓库 | 各业务团队 | 配置 Cursor Rules/MCP、CI job |
| acp-gateway | 平台团队 | MCP 配置中注入 KB server |
| code-review-bot | 平台团队 | Review Agent 增加 KB 查询步骤 |
| GitLab CI | DevOps | 添加 post-merge 索引 job |
| 统一文档仓库 (ultron-doc) | 各业务团队共同维护 | 被 KB 索引，被审计 Skill 验证 |

## 8. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 知识库服务不可用 | Agent 无法查询，但不阻塞开发 | Rule 中明确：KB 不可用时退回常规开发模式 |
| 索引数据过时 | 查询结果不准确 | CI 增量索引 + Dashboard Sync + 定期审计 |
| Token 消耗增加 | Cursor Rule 每次交互注入上下文 | Rule 保持精简（<20 行核心规则） |
| 跨服务搜索结果过多 | 干扰 Agent 判断 | 合理设置 k 值，使用 repository 过滤 |
| Token/密钥泄露 | `.cursor/mcp.json` 中含 API Token | Token 使用 viewer 权限（只读），不在代码中硬编码；CI 中使用环境变量 |
| 错误索引（repository/business 标签错误） | 数据隔离被破坏 | 索引脚本强制指定 repository 参数；Dashboard 可视化验证 |
| kb-doc-writer 与 code-review-bot 文档维护冲突 | 同一文档被两个流程同时修改 | 明确分工：bot 负责 PR 触发的自动维护，Skill 负责手动触发的全量编写 |
| CI 索引失败阻塞合并 | PR 无法合并 | CI job 设为 `allow_failure: true`，索引失败不阻塞合并 |
