# 待办事项与改进建议

**Created:** 2026-05-24
**Last Updated:** 2026-05-24

---

## 一、未实现设计提案

### 1. 多视图 Wiki 结构 [P3]

当前 Wiki 仅有"业务域视图"（`/__domains__/`）。构想三种视图：

| 视图 | 路由前缀 | 使用场景 |
|------|---------|---------|
| **业务域视图** | `/__domains__/` | 理解业务功能、跨仓库业务流 |
| **仓库视图** | `/__repos__/` | 代码导航、仓库级架构理解 |
| **技术文档** | `/__tech__/` | 技术决策参考、新人 onboarding |

**待解决**:
- 域概览 vs 主题页面的内容定位（广而浅 vs 窄而深）
- HierarchicalDecomposer 按模块聚类拆分主题（替代 `_maybe_split` 的机械 token 拆分）
- 前端视图切换 UI

### 2. Parent Domain Overview Agent 重构 [P2]

将 `compose_parent_pages_node` 重构为 Agent 模式（`ParentDomainDocAgent`）。

**核心改造**:
- 继承 `DocOrchestrator`，复用 explore → write → verify 模板方法
- 注入 Wiki 工具（`read_wiki_page`、`query_domain_dependencies` 等）
- 配置开关 `wiki.parent_overview_agent_mode: bool = True`
- 失败降级到现有直接 LLM 模式

**文件清单**: `wiki/parent_domain_doc_agent.py`(新建)、`wiki/agent_prompts.py`、`wiki/nodes/aggregate.py`、`wiki/pipeline_graph.py`、`core/config.py`

### 3. 非代码文件轻量解析 [P2]

`indexer/languages/` 新增 Dockerfile/K8s YAML/Protobuf 轻量 parser。先支持结构提取（service 名、端口、依赖），不需要完整 Tree-sitter AST。参考 Understand-Anything 的 40+ LanguageConfig。

---

## 二、域分类精度优化

### 未修复

| 优先级 | 问题 | 文件 | 说明 |
|--------|------|------|------|
| P1 | 域分类未利用叶子页面内容 | `wiki/nodes/classify.py` | `classify_domains` 只用 `business_summary`，不用已生成的叶子页面 Markdown |
| P2 | 嵌入失败 fallback 丢失语义 | `wiki/nodes/graph_domain_decompose.py` | 三级 fallback 已有（embed→TF-IDF→Louvain），但 TF-IDF 仅用 name+path |
| P3 | 前缀正则不鲁棒 | `wiki/nodes/classify.py` | `IOHandler`、`AJAXUtil` 等不匹配 |

---

## 三、管线质量与性能

### 未修复

| 优先级 | 问题 | 文件 | 说明 |
|--------|------|------|------|
| P2 | Token 预算无跨组件协调 | `wiki/token_budget.py` | `TokenBudgetResolver` 已有 `claim`/`remaining` 追踪，但 snippet 预算 `min(500+n*100,6000)` 对大域仍可能不足 |
| P3 | Python 侧过滤部分推入 Cypher | `wiki/graph_call_query.py` | names 已在 WHERE 子句，但 `(repo,name)` 对仍在 Python 侧过滤（Cypher 无法表达复合键成员关系） |
| P3 | Quality Gate 和 Healing 重复结构检查 | 多文件 | 同一页面最多检查 4 次 |

---

*本文档作为统一的待办追踪入口。已完成项归档见 `docs/REMAINING-WORK.md`。*
