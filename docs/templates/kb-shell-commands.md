# 知识库 Shell 命令模板

> 适用于无法使用 MCP 的环境（如 ACP 模式下的 Cursor Agent）。通过 shell 执行 `curl` 调用知识库 HTTP API。

## 使用方式

将以下命令模板注入到 Agent 的 Prompt 中，Agent 在需要时通过 shell 执行 curl 查询知识库。

**占位符说明**：
- `{kb_url}` — 知识库服务地址（如 `http://localhost:8100`）或 Gateway RAG 代理地址（如 `http://gateway:9090/api/v1/rag`）
- `{api_key}` — API Token（直连用 `Authorization: Bearer <token>`，Gateway 用 `X-API-Key`）

---

## 语义搜索

通过自然语言查找相关的代码/文档片段。

```bash
curl -s -X POST '{kb_url}/search' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {api_key}' \
  -d '{"query": "<自然语言搜索词>", "k": 5, "entity_type": "all"}'
```

**参数**:
- `query` — 搜索词，支持中英文，可以是类名、方法名、功能描述
- `k` — 返回结果数量（1-50，默认 10）
- `entity_type` — 过滤类型: `all`(默认) / `function` / `class` / `document`

## 图查询

查询代码结构关系（调用链、继承树、文件内容等）。

```bash
curl -s -X POST '{kb_url}/graph' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {api_key}' \
  -d '{"query_type": "<查询类型>", "name": "<实体名>", "depth": 3, "direction": "downstream"}'
```

**query_type 可选值**:

| query_type | 用途 | 必需参数 |
|-----------|------|---------|
| `call_chain` | 调用链查询 | `name` + `direction`(upstream/downstream) |
| `inheritance_tree` | 继承/实现关系 | `name` + `direction`(children/parents) |
| `class_methods` | 类的方法列表 | `name` |
| `file_entities` | 文件内的类/函数 | `file` |
| `find_entity` | 精确查找实体 | `name` |
| `module_dependencies` | 模块依赖 | `name` + `direction` |
| `graph_stats` | 索引统计 | 无 |

## 混合搜索

语义搜索 + 图扩展，获取代码片段及其上下文关系。

```bash
curl -s -X POST '{kb_url}/hybrid' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {api_key}' \
  -d '{"query": "<搜索词>", "k": 5, "expand_depth": 2}'
```

## 常见场景命令

### 查找类/方法的真实签名
```bash
curl -s -X POST '{kb_url}/search' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {api_key}' \
  -d '{"query": "RoomMoaService#createRoom", "k": 3, "entity_type": "function"}'
```

### 查看方法的调用方
```bash
curl -s -X POST '{kb_url}/graph' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {api_key}' \
  -d '{"query_type": "call_chain", "name": "createRoom", "direction": "upstream", "depth": 2}'
```

### 查看继承树
```bash
curl -s -X POST '{kb_url}/graph' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {api_key}' \
  -d '{"query_type": "inheritance_tree", "name": "BaseService", "direction": "children", "depth": 3}'
```

### 获取索引统计
```bash
curl -s -X POST '{kb_url}/graph' \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer {api_key}' \
  -d '{"query_type": "graph_stats"}'
```
