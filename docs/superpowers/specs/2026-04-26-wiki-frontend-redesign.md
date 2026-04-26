# Wiki Frontend Dashboard 重构设计方案

> 基于 Phase 0-6 后端能力，将 Dashboard 的 Wiki 部分从单仓库浏览升级为业务级知识库前端。

## 背景

后端已实现 Phase 0-6 的全部功能（树状结构、跨仓库业务级 Wiki、双视角导航、交叉引用、多格式导出、覆盖率报告、探索问题生成），但前端仍停留在单仓库 Wiki 浏览模式。本方案定义前端如何消费这些后端能力。

### 当前前端状态

- **路由**: `/wiki` 显示仓库选择器，`/wiki/:repository/*` 显示单仓库 Wiki
- **布局**: 左侧扁平页面列表 + 右侧内容（工具 Tab: page/health/insights/export）
- **导航**: 从 `GET /wiki/{repo}/pages` 加载扁平页面列表，手动构建树
- **内容渲染**: react-markdown + remark-gfm + rehype-raw + Mermaid
- **搜索**: 仓库内搜索（WikiSidebar）+ 跨仓库搜索（SearchPage）
- **未对接的后端 API**: `/wiki/tree`、`/pages/{uid}/references`、`/wiki/coverage-report`、`/wiki/export`（业务级）、`/wiki/business/generate`

## 设计决策摘要

| 决策点 | 选择 | 备注 |
|--------|------|------|
| 整体布局 | 自适应三栏（C） | 桌面三栏，平板两栏+抽屉，手机单栏 |
| 入口页面 | 混合入口（C） | 精简仪表盘 + 点击进入树状浏览 |
| Wikilink | 悬浮预览（B） | 鼠标悬停弹出预览卡片 |
| 路由兼容 | 旧路由直接去除 | 统一新路由，更新所有内部链接 |

## 整体架构

### 自适应三栏布局

```
桌面端 (lg, ≥1024px):
┌──────────────┬─────────────────────────────┬──────────────┐
│  WikiTreeNav  │     WikiPageView            │ RefsPanel    │
│  (280px)      │     (flex-1)                │ (260px,可折叠)│
│               │                             │              │
│ [业务][代码]   │  面包屑 + 元信息标签         │ 引用了:       │
│ ▼ 用户管理    │  # 页面标题                 │  → Service A │
│   ▼ 注册流程  │  markdown 内容              │  → Service B │
│     ● 当前页  │  [[wikilink]] 悬浮预览       │ 被引用:      │
│   🔍 搜索...  │  探索问题区域               │  ← Controller│
└──────────────┴─────────────────────────────┴──────────────┘

平板端 (md, 768-1023px):
┌──────────────┬──────────────────────────────────────────┐
│  WikiTreeNav  │     WikiPageView                  [refs]│
│  (240px)      │     引用面板 → 右侧抽屉按钮              │
└──────────────┴──────────────────────────────────────────┘

手机端 (sm, <768px):
┌────────────────────────────────────────────────────────┐
│ [☰]  Wiki · 用户管理 › UserController        [🔗]     │
│────────────────────────────────────────────────────────│
│     WikiPageView（全屏）                               │
│     树导航 → 汉堡菜单抽屉                              │
│     引用面板 → 底部展开区域                             │
└────────────────────────────────────────────────────────┘
```

右侧引用面板有展开/收起按钮，用户可随时隐藏。状态通过 localStorage 持久化。

### 路由设计

```
/wiki                            → 混合入口（精简仪表盘 + 领域卡片）
/wiki?path=/<树路径>              → 通过树路径打开页面
/wiki?view=code_structure         → 代码结构视图
/wiki?business_id=xxx             → 指定业务线（默认 "default"）
/wiki?tool=coverage               → 工具 Tab（coverage/export/health/insights）
```

所有 `/wiki/:repository/*` 旧路由移除，内部链接统一更新为新格式。

## 组件设计

### 新增组件

#### WikiShell（重构 WikiPage.tsx）

顶层壳组件，管理三栏布局、路由参数解析、响应式状态。

```typescript
interface WikiShellState {
  businessId: string;           // 从 URL 或 BusinessContext
  viewType: 'business_domain' | 'code_structure';
  currentPath: string | null;   // 当前页面树路径
  toolTab: 'page' | 'coverage' | 'export' | 'health' | 'insights';
  refsPanelOpen: boolean;       // 引用面板展开/收起
}
```

#### WikiTreeNav（替换 WikiSidebar 树逻辑）

从 `GET /wiki/tree` API 加载树节点。

```typescript
interface WikiTreeNavProps {
  businessId: string;
  viewType: 'business_domain' | 'code_structure';
  activePath: string | null;
  onSelectPage: (path: string) => void;
  onViewChange: (view: 'business_domain' | 'code_structure') => void;
}
```

特性：
- 顶部双 Tab: `[业务领域]` `[代码结构]`
- 树节点递归渲染：WikiSpace → WikiSection → WikiPage
- 活跃节点自动展开和高亮
- 内置搜索框（复用 `useWikiSearch`）
- 底部：IDE 偏好设置（复用现有逻辑）

#### WikiLandingPage（混合入口）

当 `path` 为空时显示。

```typescript
interface WikiLandingPageProps {
  businessId: string;
  onNavigate: (path: string) => void;
}
```

内容：
- 顶部：覆盖率概览条（`useWikiCoverage`）
- 中部：业务领域卡片网格（从树根节点的子节点生成）
- 底部：过时页面提醒 + 知识盲区 Top 5

#### WikiReferencesPanel（右侧引用面板）

```typescript
interface WikiReferencesPanelProps {
  pageUid: string;
  isOpen: boolean;
  onToggle: () => void;
}
```

内容：
- 出向引用分组（calls/inherits/cross_repo/imports/semantic/business_flow）
- 入向引用（反向链接）
- 每项：标题 + relation_type 图标 + 仓库标签
- 点击导航到目标页

#### WikiLinkPreview（悬浮预览组件）

```typescript
interface WikiLinkPreviewProps {
  path: string;              // wikilink 目标路径
  children: React.ReactNode; // 链接文字
}
```

鼠标悬停时：
- 延迟 300ms 后弹出预览卡片（避免误触）
- 预览卡片内容：标题 + importance badge + 第一段摘要 + 仓库标签
- 使用 `useWikiPage` 的缓存（React Query staleTime=30s）
- 点击直接导航

#### WikiCoverageCard（覆盖率统计卡片）

```typescript
interface WikiCoverageCardProps {
  businessId: string;
}
```

内容：
- 环形图（chart.js）：覆盖率百分比（covered vs skeleton）
- 数字卡片：core_coverage / standard_coverage / stale_page_count / knowledge_gap_count

#### WikiStaleAlert（过时警告条）

```typescript
interface WikiStaleAlertProps {
  generatedAt: string;
  isStale: boolean;
}
```

黄色警告条：`⚠️ 此页面的源代码已更新，文档可能不是最新的（上次生成: YYYY-MM-DD）`

#### WikiSuggestedQuestions（探索问题区域）

```typescript
interface WikiSuggestedQuestionsProps {
  questions: string[];
}
```

页面底部的可折叠区域，展示 3-5 个由后端模板生成的探索问题。每个问题可以发送到 AskPanel。

### 修改组件

#### MarkdownRenderer.tsx（wiki 版）

增强 wikilink 渲染：

1. 在 markdown 渲染前，预处理 `[[path]]` → 自定义 HTML 标签
2. 通过 rehype-raw 传入，用 custom component 渲染为 `<WikiLinkPreview>`
3. 链接样式：带下划线、区别于外部链接色调

#### WikiPageView（增强 WikiContent.tsx）

新增：
- 页面头部元信息：importance tier badge + enrichment level badge + 仓库标签
- `WikiStaleAlert` 条件渲染
- 底部 `WikiSuggestedQuestions` 区域
- 调用 `WikiReferencesPanel`（传入 pageUid）

#### WikiBusinessExportPanel（升级 WikiExportPanel.tsx）

升级为业务级导出：
- 格式选择器：markdown / zip / git / obsidian / mkdocs
- Git 推送配置对话框（remote_url, branch, commit_message_prefix）
- min_tier 筛选器
- view_type 选择

### 保持不变的组件

- `AskPanel.tsx` — 保持现有 Wiki Q&A 功能
- `TableOfContents.tsx` — 页面内 TOC 不变
- `WikiGlobalSearchBar.tsx` — 跨仓库搜索不变
- `WikiLintPanel.tsx` — 代码健康检查不变
- `GraphInsightsPanel.tsx` — 图谱洞察不变

## 新增 Hooks

```typescript
// hooks/useWikiTree.ts
function useWikiTree(businessId: string, viewType: string) {
  return useQuery({
    queryKey: ['wiki', 'tree', businessId, viewType],
    queryFn: () => apiClient.get(`/wiki/tree`, { params: { business_id: businessId, view: viewType } }),
  });
}

// hooks/useWikiReferences.ts
function useWikiReferences(pageUid: string) {
  return useQuery({
    queryKey: ['wiki', 'references', pageUid],
    queryFn: () => apiClient.get(`/wiki/pages/${encodeURIComponent(pageUid)}/references`),
    enabled: !!pageUid,
  });
}

// hooks/useWikiCoverage.ts
function useWikiCoverage(businessId: string) {
  return useQuery({
    queryKey: ['wiki', 'coverage', businessId],
    queryFn: () => apiClient.get(`/wiki/coverage-report`, { params: { business_id: businessId } }),
  });
}

// hooks/useBusinessWikiGenerate.ts
function useBusinessWikiGenerate() {
  return useMutation({
    mutationFn: (body: { business_id: string; language: string }) =>
      apiClient.post('/wiki/business/generate', body),
  });
}

// hooks/useBusinessWikiExport.ts
function useBusinessWikiExport() {
  return useMutation({
    mutationFn: (body: BusinessWikiExportBody) =>
      apiClient.post('/wiki/export', body),
  });
}

// hooks/useWikiSearch.ts
function useWikiSearch(query: string, businessId: string) {
  return useQuery({
    queryKey: ['wiki-search', query, businessId],
    queryFn: () =>
      apiClient.get(`/wiki/search?q=${query}&business_id=${businessId}&limit=20`),
    enabled: query.length >= 2,
  });
}

// hooks/useWikiAnnotations.ts
function useWikiAnnotations(pageUid: string) {
  const query = useQuery({
    queryKey: ['wiki-annotations', pageUid],
    queryFn: () => apiClient.get(`/wiki/pages/${pageUid}/annotations`),
  });
  const create = useMutation({
    mutationFn: (body: Omit<WikiAnnotation, 'annotation_id' | 'created_at'>) =>
      apiClient.post(`/wiki/pages/${pageUid}/annotations`, body),
  });
  const remove = useMutation({
    mutationFn: (annotationId: string) =>
      apiClient.delete(`/wiki/annotations/${annotationId}`),
  });
  return { ...query, create, remove };
}

// hooks/useWikiVersions.ts
function useWikiVersions(pageUid: string) {
  return useQuery({
    queryKey: ['wiki-versions', pageUid],
    queryFn: () => apiClient.get(`/wiki/pages/${pageUid}/versions`),
  });
}

// hooks/useWikiDiff.ts
function useWikiDiff(pageUid: string, fromVersion: number, toVersion: number) {
  return useQuery({
    queryKey: ['wiki-diff', pageUid, fromVersion, toVersion],
    queryFn: () =>
      apiClient.get(`/wiki/pages/${pageUid}/diff?from=${fromVersion}&to=${toVersion}`),
    enabled: fromVersion > 0 && toVersion > 0,
  });
}

// hooks/useWikiEvents.ts
function useWikiEvents(businessId: string, onEvent: (event: WikiEvent) => void) {
  useEffect(() => {
    const source = new EventSource(`/api/v1/wiki/events?business_id=${businessId}`);
    source.onmessage = (e) => onEvent(JSON.parse(e.data));
    return () => source.close();
  }, [businessId, onEvent]);
}
```

## TypeScript 类型扩展

```typescript
// hooks/wikiTypes.ts 新增
interface WikiTreeNode {
  uid: string;
  title: string;
  label: string;     // "WikiSpace" | "WikiSection" | "WikiPage"
  depth: number;
  sort_order: number;
  path: string;
  page_type: string;
}

interface WikiReferencesResponse {
  page_uid: string;
  outgoing: WikiReference[];
  incoming: WikiReference[];
}

interface WikiReference {
  target_uid: string;
  target_title: string;
  target_path: string;
  relation_type: string;
  context: string;
  repository: string;
}

interface WikiCoverageResponse {
  total_entities: number;
  covered_entities: number;
  coverage_percentage: number;
  core_coverage: number;
  standard_coverage: number;
  stale_pages: WikiStalePage[];
  stale_page_count: number;
  knowledge_gaps: WikiKnowledgeGap[];
  knowledge_gap_count: number;
}

interface WikiStalePage {
  page_path: string;
  page_title: string;
  entity_commit: string;
  page_generated_at: string;
}

interface WikiKnowledgeGap {
  entity: string;
  in_degree: number;
  wiki_tier: string | null;
}

interface BusinessWikiExportBody {
  business_id: string;
  format: 'markdown' | 'zip' | 'git' | 'obsidian' | 'mkdocs';
  view_type: 'business_domain' | 'code_structure' | 'both';
  min_tier: 'core' | 'standard' | 'skeleton';
  git_config?: {
    remote_url: string;
    branch: string;
    commit_message_prefix: string;
  };
}

// Phase 8~10 新增类型

interface WikiSearchResult {
  page_path: string;
  page_title: string;
  snippet: string;
  highlight_ranges: Array<{ start: number; end: number }>;
  score: number;
}

interface WikiAnnotation {
  annotation_id: string;
  page_uid: string;
  text_range_start: number;
  text_range_end: number;
  comment: string;
  author: string;
  created_at: string;
}

interface WikiVersion {
  version: number;
  content_hash: string;
  generated_at: string;
  change_summary: string;
}

interface WikiDiff {
  from_version: number;
  to_version: number;
  hunks: Array<{
    old_start: number;
    old_lines: number;
    new_start: number;
    new_lines: number;
    content: string;
  }>;
}

type WikiEventType =
  | 'wiki:page_updated'
  | 'wiki:generation_started'
  | 'wiki:generation_completed'
  | 'wiki:generation_failed';

interface WikiEvent {
  type: WikiEventType;
  business_id: string;
  page_path?: string;
  timestamp: string;
  payload?: Record<string, unknown>;
}
```

## 数据流

```
用户访问 /wiki
  │
  ├─ path 为空 → WikiLandingPage
  │    ├─ useWikiCoverage(businessId) → 覆盖率概览
  │    └─ useWikiTree(businessId, viewType) → 领域卡片
  │
  └─ path 有值 → WikiPageView + WikiReferencesPanel
       ├─ useWikiTree(businessId, viewType) → 左侧树
       ├─ useWikiPage(path) → 中间内容
       └─ useWikiReferences(pageUid) → 右侧引用

视角切换: viewType 变更 → useWikiTree 重新查询 → 树重新渲染
Wikilink 点击: 更新 URL ?path=xxx → WikiPageView 重新渲染

搜索: Cmd+K → WikiSearchBar → useWikiSearch(query, businessId) → WikiSearchResults
       → 点击结果 → 更新 URL ?path=xxx

SSE 实时更新:
  useWikiEvents(businessId) → EventSource
    ├─ wiki:page_updated → WikiUpdateNotification toast → 用户点击刷新
    ├─ wiki:generation_started → WikiGenerationProgress 显示进度
    ├─ wiki:generation_completed → WikiGenerationProgress 完成 + 刷新树
    └─ wiki:generation_failed → 错误 toast

标注流: 用户选中文本 → WikiAnnotationLayer 弹出工具栏 → useWikiAnnotations.create
        → WikiAnnotationSidebar 实时更新

版本对比: WikiVersionBadge 点击 → WikiVersionHistory → 选择两个版本
          → useWikiDiff(uid, v1, v2) → WikiDiffViewer
```

## 实施阶段

### FE-Phase 1: 基础设施
- 新增 TypeScript 类型定义（wikiTypes.ts 扩展）
- 新增 11 个 hooks（useWikiTree, useWikiReferences, useWikiCoverage, useBusinessWikiGenerate, useBusinessWikiExport, useWikiSearch, useWikiAnnotations, useWikiVersions, useWikiDiff, useWikiEvents）
- BusinessContext 增强（如有必要）
- Wikilink 解析工具函数

### FE-Phase 2: 树状导航 + 全文搜索
- WikiTreeNav 组件（替换 WikiSidebar 树逻辑）
- 双视角 Tab 切换（业务域/代码结构）
- 树节点展开/折叠 + 活跃节点高亮
- WikiSearchBar 组件（嵌入 WikiShell 顶栏，支持 Cmd+K 快捷键唤起）
- WikiSearchResults 组件（搜索结果列表 + 关键词高亮 + 点击跳转 Wiki 页面）
- useWikiSearch(query, businessId) Hook — 调用搜索 API 并按 wiki scope 过滤

### FE-Phase 3: 混合入口页
- WikiLandingPage 组件
- WikiCoverageCard 组件（环形图）
- 领域快捷卡片
- 路由重构（移除旧路由，统一新路由）
- 更新所有内部链接引用

### FE-Phase 4: 页面内容增强
- MarkdownRenderer wikilink 解析增强
- WikiLinkPreview 悬浮预览组件
- 页面头部元信息（importance/enrichment badges）
- WikiStaleAlert 过时警告

### FE-Phase 5: 引用面板
- WikiReferencesPanel 组件
- 自适应折叠/抽屉行为
- 引用分组 + 图标 + 点击导航

### FE-Phase 6: 探索问题 + 导出升级
- WikiSuggestedQuestions 组件
- WikiBusinessExportPanel（多格式导出）
- Git 推送配置对话框

### FE-Phase 7: 测试（基础）
- FE-Phase 1~6 组件单元测试（Vitest + React Testing Library）
- Hook 测试（Mock API 响应）
- E2E 测试（关键导航流程：树浏览、搜索、引用面板、导出）

### FE-Phase 8: Wiki 内容编辑与标注
- WikiEditButton 组件 — 「Edit on GitHub/GitLab」按钮，链接到导出后的 Git 仓库对应文件
  - 前提：FE-Phase 5 导出/Git push 完成后才可生成有效链接
  - 自动拼接 URL：`{git_remote_url}/blob/{branch}/{export_path}`
- WikiAnnotationLayer 组件 — 内容区域的标注叠加层，用户选中文本后弹出标注工具栏
- WikiAnnotationSidebar 组件 — 侧边栏展示当前页面所有标注（类似 Google Docs 评论）
- useWikiAnnotations(pageUid) Hook — 标注的 CRUD 操作

### FE-Phase 9: Wiki 版本对比
- WikiVersionBadge 组件 — 页面头部显示当前版本号 + 最后更新时间
- WikiVersionHistory 组件 — 时间线形式展示版本列表
- WikiDiffViewer 组件 — 左右对比 / 统一 diff 视图（基于 react-diff-viewer-continued）
- useWikiVersions(pageUid) Hook — 获取版本历史列表
- useWikiDiff(pageUid, fromVersion, toVersion) Hook — 获取两版本间的 diff

### FE-Phase 10: SSE 实时更新通知
- useWikiEvents(businessId) Hook — EventSource 监听 SSE 事件流
- WikiUpdateNotification 组件 — toast / 顶部 banner 提示「Wiki 页面已更新，点击刷新」
- WikiGenerationProgress 组件 — 后台生成时显示进度条 + 阶段信息
- 事件类型：wiki:page_updated, wiki:generation_started, wiki:generation_completed, wiki:generation_failed

### FE-Phase 11: 测试（扩展）
- FE-Phase 8~10 组件单元测试
- 标注 CRUD 集成测试
- SSE 连接模拟测试
- 版本对比 snapshot 测试

## 错误处理

- **树 API 无数据**: 降级为仓库选择器（现有行为）
- **引用 API 失败**: 引用面板显示空状态提示，不影响内容阅读
- **覆盖率 API 失败**: 隐藏覆盖率卡片，不影响导航
- **Wikilink 目标不存在**: 渲染为灰色禁用链接 + tooltip 提示"页面尚未生成"
- **搜索 API 失败**: 搜索结果区域显示"搜索暂不可用"，不影响树导航
- **SSE 连接断开**: 自动重连（指数退避），静默恢复，不弹 toast
- **标注 API 失败**: 标注操作显示 inline 错误提示，不影响内容阅读
- **版本 API 失败**: 版本历史区域显示空状态，不影响当前版本内容

## 向后兼容

不保留旧路由。`/wiki/:repository/*` 格式直接移除，所有内部链接（FileExplorer、PrImpactPage、CommandPalette、QuickStartBanner、ArchitecturePage 等）统一更新为 `/wiki?path=...` 或 `/wiki` 格式。

## 后端补充需求

### 探索问题 API（FE-Phase 6 前置）

当前 `SuggestedQuestionsGenerator` 是纯 Python 工具类，缺少 API 端点。

**需新增**: `GET /api/v1/wiki/pages/{page_uid}/suggested-questions`

调用 `SuggestedQuestionsGenerator.generate()` 并从图谱查询 `PageContext`。

### 页面过时状态（FE-Phase 4）

前端从 coverage report 的 stale_pages 列表中匹配当前页面路径判断是否过时，无需后端修改。

### Wiki 全文搜索 API（FE-Phase 2 前置）

**需新增**: `GET /api/v1/wiki/search?q={query}&business_id={id}&limit=20`

复用现有 hybrid retrieval (RRF) 能力，增加 wiki scope 过滤，返回结果包含 page_path、标题、匹配片段和高亮位置。

### 标注存储 API（FE-Phase 8 前置）

**需新增**:
- `POST /api/v1/wiki/pages/{page_uid}/annotations` — 创建标注
- `GET /api/v1/wiki/pages/{page_uid}/annotations` — 获取页面所有标注
- `DELETE /api/v1/wiki/annotations/{annotation_id}` — 删除标注

标注数据模型：`WikiAnnotation` 节点（annotation_id, page_uid, text_range_start, text_range_end, comment, author, created_at）。

### 版本历史 API（FE-Phase 9 前置）

**需新增**:
- `GET /api/v1/wiki/pages/{page_uid}/versions` — 获取版本历史列表
- `GET /api/v1/wiki/pages/{page_uid}/diff?from={v1}&to={v2}` — 获取两版本间的 diff

WikiPage 已有 version + content_hash 字段，后端需补充版本快照存储机制。

### SSE 事件流端点（FE-Phase 10 前置）

**需新增**: `GET /api/v1/wiki/events?business_id={id}`

SSE 事件流端点，推送以下事件类型：
- `wiki:page_updated` — 单页更新完成
- `wiki:generation_started` — 开始批量生成
- `wiki:generation_completed` — 批量生成完成
- `wiki:generation_failed` — 生成失败

## 不在本提案范围内

（无 — 原列出的四项功能已全部纳入上述 Phase 规划）
