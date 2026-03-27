# 业务项目接入指南：知识库服务（KB）

本文档面向**业务仓库开发者**，说明如何在 Cursor IDE 中快速接入 [knowledge-base-service](../README.md)（以下简称 KB），在编写代码时通过 MCP 查询跨服务接口与真实代码上下文。

## 概述

知识库服务提供基于代码图与向量检索的 **RAG 查询能力**（如 `rag_query`、`rag_graph`），将多仓库源码与文档索引为可检索的知识图谱。业务侧接入后，可在 Cursor Agent 中优先使用真实定义与调用关系，**减少臆造 API、降低跨服务协作中的理解偏差**。

## 前置条件

| 项目 | 说明 |
|------|------|
| **KB 服务地址** | 默认 `http://localhost:8100`；生产/联调环境以运维或平台提供的地址为准。 |
| **访问令牌** | 需向**管理员**申请 API Token，并确认角色为 **editor**（可触发索引等写操作）或 **viewer**（只读查询）。 |
| **仓库已纳入索引** | 在浏览器打开 KB 的 **`/dashboard`** 查看仓库列表，或调用 `GET /api/v1/repositories` 确认你的业务仓库已在列表中且状态正常。 |

更多架构与能力说明见 [README.md](../README.md)。

---

## Step 1：索引你的仓库

1. **触发全量索引**（任选其一）  
   - 执行仓库内脚本：`scripts/index-services.sh`（按项目约定配置仓库与参数）  
   - 或在 **Dashboard** 中对目标仓库执行「全量/重建」类索引操作  

2. **验证索引与图数据**（将 `your-repo` 换为你的仓库标识；将主机名换为实际 KB 地址）：

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://kb-service:8100/api/v1/graph/stats?repository=your-repo"
```

若返回统计信息正常，说明该仓库图数据已就绪，可进入 MCP 配置。

---

## Step 2：配置 Cursor MCP

1. 将模板 [docs/templates/mcp-config.json](./templates/mcp-config.json) 复制到**业务项目**根目录下的 `.cursor/mcp.json`（若不存在 `.cursor` 目录请先创建）。  
2. 编辑其中的 **`url`**（指向 KB 的 MCP 端点，一般为 `http(s)://<kb-host>:8100/api/v1/mcp`）和 **`Authorization: Bearer <token>`**。  

**说明：** 若 Token 已与某个业务线/租户绑定，通常**无需**再传 `X-Business-Id`；若平台另有要求，以管理员说明为准。

完整参数、工具列表与排错见 [MCP 集成文档](./MCP-INTEGRATION.md)。

---

## Step 3：安装 Cursor Rules

将规则模板复制到**业务项目**的 `.cursor/rules/` 目录：

| 操作 | 说明 |
|------|------|
| **建议必装** | 复制 [knowledge-base-coding.mdc](./templates/knowledge-base-coding.mdc) → `.cursor/rules/knowledge-base-coding.mdc` |
| **可选** | 复制 [knowledge-base-docs.mdc](./templates/knowledge-base-docs.mdc) → `.cursor/rules/knowledge-base-docs.mdc` |

**规则作用简述：**

- **knowledge-base-coding.mdc**：在 Java/Python/Go/TS/JS 等代码文件中，要求 Agent 在跨服务调用、不确定 API 签名等场景下**优先通过 MCP 查询知识库**（`rag_query` / `rag_graph`），并给出查询策略与降级说明。  
- **knowledge-base-docs.mdc**：在 Markdown/RST 文档中，要求编写前检索已有文档与真实代码引用，维护文档与代码一致性，并在适当时机触发增量索引相关指引。

---

## Step 4：验证接入

1. 在 Cursor 中打开业务仓库中的任意代码文件。  
2. 对 Agent 提出一个需要**跨服务/跨模块**真实信息的问题，例如：「请查询某某服务对外暴露的接口定义及调用方」。  
3. 确认 Agent **调用了 MCP 工具链中的 `rag_query`（或按集成文档所示的等价查询工具）**，且返回内容来自知识库（含类名、路径、片段等），而非纯推测。  

若始终无 MCP 调用，请检查 `.cursor/mcp.json`、Cursor MCP 是否已启用，以及 Token 与网络是否可达（详见 [MCP-INTEGRATION.md](./MCP-INTEGRATION.md)）。

---

## 常见问题（FAQ）

| 问题 | 处理建议 |
|------|----------|
| **KB 不可用或超时** | Agent 应按规则**自动降级**（例如仅基于本地仓库推理）；恢复服务后重新查询。检查 VPN、防火墙、KB 地址与端口。 |
| **如何更新索引** | 代码变更后使用 **增量索引** 或平台提供的 **同步/触发任务**（具体以 Dashboard 与运维文档为准）；大版本或结构变更后可考虑**全量重建**。 |
| **检索结果不准或过时** | 先确认**索引时间**与分支是否匹配；必要时对对应仓库**重新索引或全量重建**，再缩小查询范围（仓库、路径、FQN）。 |
| **Token 无效、403、权限不足** | 核对 Token 是否过期、角色是否为 editor/viewer；若使用业务绑定 Token，确认环境与业务线一致；仍失败请联系**管理员**重置或授权。 |

---

## 最佳实践

### 检索策略优先级（建议）

| 优先级 | 策略 | 适用场景 |
|:------:|------|----------|
| 1 | **FQN**（完整限定名，如 `com.example.Service#method`） | 已知类/方法名，需要精确定义与位置 |
| 2 | **关键词** | 已知模块、配置项、错误码等短词 |
| 3 | **语义/自然语言** | 只有功能描述，不确定符号名 |
| 4 | **图查询（graph）** | 调用链、继承关系、上下游影响分析 |

### 常用 Prompt 示例

1. 「请用知识库查询 `OrderService#create` 的完整方法签名及所在文件。」  
2. 「在仓库 A 与 B 之间，支付回调接口的 HTTP 路径和请求体字段来自哪里？请用 `rag_query` 给出引用片段。」  
3. 「列出调用 `UserFacade#getProfile` 的上游服务或类，并用图查询说明影响范围。」  
4. 「这段改动会动到公共 RPC，请先从知识库确认现有调用链再给出修改建议。」  
5. 「写接口文档前，请检索知识库里是否已有同名接口说明，避免重复。」  

---

## 相关链接

- [项目架构与快速开始](../README.md)  
- [MCP 集成详解](./MCP-INTEGRATION.md)  
- [配置与规则模板](./templates/)  
