---
name: kb-doc-auditor
description: 审计项目文档的准确性，通过知识库验证文档中的代码引用是否与真实代码一致。按需激活。
---

# KB Doc Auditor

通过知识库验证项目文档中所有代码引用的准确性，生成审计报告。适用于定期检查或大规模代码变更后的文档健康度评估。

## 前提条件

- 项目已被知识库索引且索引是最新的
- Cursor MCP 已配置 `knowledge-base` 连接

## 工作流

### Step 1: 扫描文档目录

遍历目标 `docs/` 下所有 `.md` 文件，建立待审计文件清单：

```bash
find docs/ -name "*.md" -type f | sort
```

如果项目有 README.md，也纳入审计范围。

### Step 2: 提取代码引用

对每个文档文件，提取其中提到的代码引用：

- **类名**：大写开头的驼峰词（如 `AuthService`、`OrderController`）
- **方法名**：`类名#方法名` 或 `类名.方法名` 格式
- **FQN**：完全限定名（如 `com.example.service.AuthService`）
- **代码块中的签名**：```java/python/go 代码块中的类/方法声明
- **文件路径引用**：`src/main/java/...` 格式的路径

### Step 3: 逐项验证

对每个提取的代码引用，通过 KB 验证其准确性：

**类名/方法名验证**：
```
rag_query(query="<类名或方法名>", k=3, entity_type="class")  # 或 "function"
rag_graph(query_type="find_entity", name="<实体名>", entity_type="any")
```

**FQN 验证**：
```
rag_query(query="<完整FQN>", k=1, entity_type="all")
```

**签名验证**：
查询到实体后，对比文档中写的签名与 KB 返回的 `signature` 字段是否一致。

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

```
rag_index(directory="<项目路径>", mode="incremental")
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
