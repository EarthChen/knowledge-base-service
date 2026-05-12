# 多视图 Wiki 结构构想

**Created:** 2026-05-12  
**Status:** Idea (待后续提案)  
**Priority:** P3  
**Type:** 构想记录

---

## 背景

当前 Wiki 仅有"业务域视图"（`/__domains__/`），按 LLM 分类的业务域组织文档。讨论中识别出需要多种视图来满足不同使用场景。

## 构想的三种视图

| 视图 | 路由前缀 | 内容 | 使用场景 |
|------|---------|------|---------|
| **业务域视图** | `/__domains__/` | 按业务域组织的文档 | 理解业务功能、跨仓库业务流 |
| **仓库视图** | `/__repos__/` | 按仓库组织的模块文档 | 代码导航、仓库级架构理解 |
| **技术文档** | `/__tech__/` | 架构图、技术方案、API 文档 | 技术决策参考、新人 onboarding |

## 关键设计点

- 现有 `view=business_domain` 路由参数已为多视图预留扩展点
- 域分类 v2 的 slug 体系可以复用到仓库视图和技术文档
- 仓库视图可以直接从图数据库中的 Module 节点生成，无需额外 LLM 分类
- 技术文档可能需要不同的 Agent prompt 和生成策略

## 依赖

- 域分类 v2（slug 体系、锚定机制）需先完成
- 前端需要支持视图切换 UI

## 待固化：域概览 vs 主题页面的内容定位

当前 DomainDocAgent 生成一个长页面，混合了高层概述和代码细节。理想模型：

- **域概览**（`_overview`）：广而浅——域做什么、包含哪些能力、模块间如何协作。每个能力只用一句话 + wikilink 引导到主题页。
- **主题页面**：窄而深——展开域概览中某一能力的详细代码逻辑、数据流、调用链路。

改造方向：
1. HierarchicalDecomposer 按模块聚类拆分主题（而非当前 `_maybe_split` 的机械 token 拆分）
2. DomainDocAgent 区分"概览模式"（只写导航概述）和"主题模式"（深入代码分析）
3. 每个主题由 Agent 独立生成，explore 范围限定在该主题的模块子集内

## 待固化：Agent 组件抽象化

当前每个功能都从头实现一个 Agent（DomainDocAgent、WikiPageAgent、未来可能的 TopicDocAgent、BusinessFlowAgent）。应该抽象出可复用的 Agent 基础组件：

- **共享的 Explore/Write 引擎**：`WikiPageAgent` 的 explore + write + WorkingMemory 应成为基础组件
- **可插拔的 Prompt 策略**：不同 Agent 只需提供不同的 system prompt + baseline 构建逻辑
- **共享的工具集**：read_code、search_entities、grep_code 等工具在所有 Agent 间通用
- **共享的 Quality Gate**：content 质量评估逻辑应可配置但不重复实现

目标：新增一种文档类型（如 TopicDoc、BusinessFlowDoc）只需定义 Prompt + baseline 策略，不需要新建整个 Agent 类。

## 下一步

等域分类 v2 实施完成并验证后，启动独立提案。
