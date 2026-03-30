---
name: kb-doc-auditor
description: 审计项目文档的准确性，通过知识库验证文档中的代码引用是否与真实代码一致。支持 MCP 和 Python 脚本双模式，自动检测 MCP 可用性。
---

# KB Doc Auditor

通过知识库验证项目文档中所有代码引用的准确性，生成审计报告。适用于定期检查或大规模代码变更后的文档健康度评估。

## 环境适配

本 Skill 支持两种 KB 查询方式，Agent 按以下优先级**自动检测**并选择：

**自动检测流程：**

1. **显式指定检查**：如果 Prompt 中包含 `[KNOWLEDGE BASE - SHELL QUERY TOOLS]`，直接使用脚本模式
2. **MCP 可用性探测**：尝试调用任意一个 MCP KB 工具（推荐 `rag_graph(query_type="graph_stats")`）
   - 调用成功 → 使用 **MCP 模式**
   - 工具不存在 / 连接失败 / 超时 → 自动降级为 **脚本模式**

| 模式 | 触发条件 | 查询方式 |
|------|----------|----------|
| MCP 模式 | MCP `knowledge-base` 工具可用且响应正常 | MCP 工具调用 |
| 脚本模式（默认降级） | MCP 不可用，或显式指定 Shell 模式 | `scripts/kb_query.py` Python 脚本 |

> **注意**：检测只需在 Step 1 时执行一次，后续步骤沿用检测结果。如果中途 MCP 断开，切换到脚本模式继续执行。

下文每个查询步骤同时提供两种写法，使用 `MCP:` 和 `Shell:` 标签区分。

### 脚本使用方式

当 MCP 不可用时，通过本 Skill 附带的 `scripts/kb_query.py` 脚本查询知识库。

**配置方式（二选一）：**

方式一：在项目根目录创建 `.env` 文件（推荐）：
```
KB_URL=http://localhost:8100/api/v1
KB_TOKEN=your-api-token
```

方式二：设置环境变量：
```bash
export KB_URL="http://localhost:8100/api/v1"
export KB_TOKEN="your-api-token"
```

脚本会按优先级加载配置：`.env` 文件 → 环境变量 → 默认值。环境变量可覆盖 `.env` 中的值。

脚本无第三方依赖（仅使用 Python 标准库），支持全部查询类型。添加 `--brief` 输出人类可读摘要：

```bash
python3 scripts/kb_query.py --brief search "AuthService"
python3 scripts/kb_query.py --help
```

## 前提条件

- 项目已被知识库索引且索引是最新的
- MCP 模式：Cursor MCP 已配置 `knowledge-base` 连接（`.cursor/mcp.json`）
- 脚本模式：设置 `KB_URL` 和 `KB_TOKEN` 环境变量（或 `.env` 文件）

## 查询精度规则（强制）

> **所有 KB 查询必须使用全限定名（FQN）。** 这不是建议，而是强制要求。使用简单类名会导致同名实体干扰，返回错误结果。

**强制规则：**

1. **所有查询必须使用 FQN**：查询 `com.example.service.AuthService` 而非 `AuthService`。Agent 必须在 Step 2 中推断出每个引用的 FQN，并在 Step 3 中用 FQN 执行查询
2. **FQN 推断方法**（按优先级尝试）：
   - 文档中已有的 FQN 或 import 声明 → 直接使用
   - 文档中的文件路径引用 → 从路径推断（如 `src/main/java/com/example/service/AuthService.java` → `com.example.service.AuthService`）
   - 代码块中的 package 声明 → 拼接 package + 类名
   - 以上均无 → **先做一次预查询获取 FQN**，再用 FQN 执行正式验证
3. **多仓库环境**：先通过 `repos` 确认目标仓库，查询结果中验证 `file` 路径属于目标项目
4. **结果路径过滤**：返回多个结果时，通过 `file` 字段中的模块路径排除非目标项目的同名实体

**确认仓库（多仓库场景必须先执行）：**

**MCP:**
```
rag_query(query="<项目名>", k=1, entity_type="all")
```

**Shell:**
```bash
python3 scripts/kb_query.py repos
python3 scripts/kb_query.py search "<项目名>" --k 1
```

## 工作流

### Step 1: 扫描文档目录

遍历目标 `docs/` 下所有 `.md` 文件，建立待审计文件清单：

```bash
find docs/ -name "*.md" -type f | sort
```

如果项目有 README.md，也纳入审计范围。

### Step 2: 提取代码引用并推断 FQN

对每个文档文件，提取其中提到的代码引用，**并为每个引用推断其全限定名（FQN）**：

**2a. 提取原始引用：**

- **类名**：大写开头的驼峰词（如 `AuthService`、`OrderController`）
- **方法名**：`类名#方法名` 或 `类名.方法名` 格式
- **FQN**：完全限定名（如 `com.example.service.AuthService`）
- **代码块中的签名**：```java/python/go 代码块中的类/方法声明
- **文件路径引用**：`src/main/java/...` 格式的路径

**2b. 推断 FQN（必须）：**

对每个提取的简单类名/方法名，必须尝试推断其 FQN：

| 文档中的线索 | 推断方法 | 示例 |
|-------------|---------|------|
| 已有 FQN | 直接使用 | `com.example.service.AuthService` |
| 文件路径 `src/main/java/com/example/service/AuthService.java` | 路径转换 | → `com.example.service.AuthService` |
| 代码块含 `package com.example.service` | package + 类名 | → `com.example.service.AuthService` |
| import 语句 `import com.example.service.AuthService` | 直接提取 | → `com.example.service.AuthService` |
| 以上均无 | **预查询获取 FQN** | 见下方 |

**预查询获取 FQN**（当文档无足够上下文时）：

**MCP:**
```
rag_graph(query_type="find_entity", name="AuthService", entity_type="class")
```

**Shell:**
```bash
python3 scripts/kb_query.py --brief graph find_entity --name "AuthService" --entity-type class
```

从返回结果的 `file` 字段推断 FQN（如 `file: src/main/java/com/example/service/AuthService.java` → FQN: `com.example.service.AuthService`），并验证 `file` 路径属于目标项目。

**2c. 输出格式：**

建立待验证清单，每项必须包含 FQN：

```
| 文档文件 | 原始引用 | 推断的 FQN | 来源 |
|---------|---------|-----------|------|
| docs/api.md | AuthService | com.example.service.AuthService | 文件路径推断 |
| docs/api.md | OrderService#createOrder | com.example.order.OrderService#createOrder | 预查询 |
```

### Step 3: 使用 FQN 逐项验证

对 Step 2 清单中的每个引用，**必须使用其 FQN 进行查询**。禁止直接使用简单类名作为最终验证查询。

**3a. FQN 精确验证（所有引用必须执行）：**

**MCP:**
```
rag_query(query="com.example.service.AuthService", k=1, entity_type="all")
```

**Shell:**
```bash
python3 scripts/kb_query.py search "com.example.service.AuthService" --k 1
```

**3b. 方法级验证（文档中引用了具体方法时）：**

**MCP:**
```
rag_query(query="com.example.service.AuthService#authenticate", k=1, entity_type="function")
rag_graph(query_type="class_methods", name="com.example.service.AuthService")
```

**Shell:**
```bash
python3 scripts/kb_query.py search "com.example.service.AuthService#authenticate" --type function --k 1
python3 scripts/kb_query.py graph class_methods --name "com.example.service.AuthService"
```

**3c. 结果验证：**

- 检查返回结果的 `file` 路径是否属于目标项目（排除其他仓库同名实体）
- 对比文档中写的签名与 KB 返回的 `signature` 字段是否一致
- 如果 FQN 查询无结果，用 `find_entity` 确认实体是否已被删除/重命名：

**MCP:**
```
rag_graph(query_type="find_entity", name="AuthService", entity_type="any")
```

**Shell:**
```bash
python3 scripts/kb_query.py --brief graph find_entity --name "AuthService"
```

### Step 4: 标记结果

对每个代码引用标记验证结果：

| 标记 | 含义 | 处理建议 |
|------|------|----------|
| `[✅ 准确]` | KB 中存在且签名一致 | 无需操作 |
| `[⚠️ 签名已变更]` | 实体存在但签名/参数不匹配 | 更新文档中的签名 |
| `[🚫 已删除/重命名]` | KB 中找不到该实体 | 确认是否已删除或重命名，更新或移除引用 |
| `[❓ 无法确认]` | KB 查询失败或结果模糊 | 需人工确认 |

### Step 5: 生成审计报告

输出结构化审计报告，格式如下：

```markdown
# 文档审计报告

**审计时间**: YYYY-MM-DD HH:MM
**审计范围**: docs/ (N 个文件)
**知识库版本**: <最近一次索引时间>

## 总览

| 状态 | 数量 | 占比 |
|------|------|------|
| ✅ 准确 | X | X% |
| ⚠️ 签名已变更 | X | X% |
| 🚫 已删除/重命名 | X | X% |
| ❓ 无法确认 | X | X% |

## 详细发现

### docs/api.md

- ✅ `AuthService#authenticate` — 签名一致
- ⚠️ `OrderService#createOrder` — 参数已变更
  - 文档: `createOrder(String orderId, int quantity)`
  - 实际: `createOrder(CreateOrderRequest request)`
- 🚫 `LegacyHelper#convert` — 代码中已不存在

### docs/architecture.md
...

## 建议操作

1. [高优先级] 更新 docs/api.md 中 OrderService#createOrder 的签名
2. [中优先级] 移除 docs/api.md 中对 LegacyHelper 的引用
...
```

### Step 6: 修复（可选）

如果用户确认，可直接修复文档中的不准确引用：

1. 对 `[⚠️ 签名已变更]` 项，用 KB 返回的最新签名替换文档中的旧签名
2. 对 `[🚫 已删除/重命名]` 项，移除引用或用 KB 搜索替代实体
3. 修复后重新执行 Step 3 验证

### Step 7: 索引更新的文档

如果执行了 Step 6 修复：

**MCP:**
```
rag_index(directory="<项目路径>", mode="incremental")
```

**Shell:**
```bash
python3 scripts/kb_query.py index "<项目路径>"
```

## 推荐执行频率

| 场景 | 频率 |
|------|------|
| 常规维护 | 每月一次 |
| 大规模重构后 | 立即执行 |
| 版本发布前 | 必须执行 |
| 新接手项目 | 首次执行一次了解文档健康度 |

## 降级策略

KB 不可用时无法执行审计（审计的核心价值就是 KB 交叉验证）。等待 KB 服务恢复后再执行。
