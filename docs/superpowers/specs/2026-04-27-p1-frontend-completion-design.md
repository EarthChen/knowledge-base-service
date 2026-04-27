# P1 — 前端补全设计

> 状态：已批准 2026-04-27

## 背景

Phase 0-3 实施了完整的后端能力，但对应的前端组件尚未实现。本阶段补全前端，使用户能直接使用 Wiki 编辑、推理可视化、层级过滤和离线下载功能。

## 目标

实现 4 个新前端组件 + 提升测试覆盖率至 70%。

---

## Task 4: WikiEditor 富文本编辑器

### 设计

在 `WikiContent` 组件中添加"编辑"模式切换。

**技术选型**：`@uiw/react-codemirror` (Markdown 语法高亮)

**布局**：Split View
- 左侧：CodeMirror Markdown 编辑器
- 右侧：实时预览（复用 `MarkdownRenderer`）
- 底部：保存按钮 + 版本冲突提示

**数据流**：
1. 用户点击 "Edit" → 切换到编辑模式，加载当前 content
2. 编辑时左侧实时更新，右侧预览通过 debounce 同步
3. 保存时调用 `PATCH /api/v1/wiki/pages/{page_uid}/content`
4. 传递 `expected_version` 实现乐观并发控制
5. 如果版本不匹配，显示警告并允许强制覆盖或刷新

**文件规划**：
- `dashboard/src/components/wiki/WikiEditor.tsx` (新建)
- `dashboard/src/components/wiki/WikiContent.tsx` (修改：添加编辑模式切换)
- `dashboard/src/hooks/useWikiPageEdit.ts` (新建：PATCH mutation hook)

---

## Task 5: ReasoningPathPanel 推理路径可视化

### 设计

在 `AskPanel` 答案区域下方显示可折叠的推理路径面板。

**数据来源**：`wiki-answer-complete` SSE 事件中的 `reasoning_path` 字段

**UI 结构**：
```
[▼ 推理路径]
  ┌─ search (vector) ──→ AuthService, TokenManager, UserRepo [0.92]
  │
  ├─ graph_expand (graph) ──→ JWTValidator, SessionStore [0.85]
  │
  └─ answer_entities: AuthService, TokenManager, JWTValidator
```

- 每个 stage 显示为卡片：stage_name、retriever 类型 badge、entity_hits 列表、score 进度条
- `answer_entities` 高亮显示出现在答案中的实体
- 垂直流程布局（CSS flexbox + 连接线），无需 xyflow 依赖

**文件规划**：
- `dashboard/src/components/wiki/ReasoningPathPanel.tsx` (新建)
- `dashboard/src/components/wiki/AskPanel.tsx` (修改：集成 panel)

---

## Task 6: WikiTierSelector 层级过滤

### 设计

在 `WikiTreeNav` 的视图切换（business_domain / code_structure）旁添加层级下拉选择器。

**选项**：
- Comprehensive（全部页面）
- Standard（排除 skeleton + supplementary）
- Essential（仅 core + essential）

**实现**：
- `wiki_tier` 作为 URL 查询参数持久化
- 切换时重新请求 tree API: `GET /wiki/tree?wiki_tier=standard`
- 默认值：`null`（等同 comprehensive）

**文件规划**：
- `dashboard/src/components/wiki/WikiTierSelector.tsx` (新建)
- `dashboard/src/components/wiki/WikiTreeNav.tsx` (修改：集成选择器)
- `dashboard/src/hooks/useWikiTree.ts` (修改：传递 wiki_tier 参数)

---

## Task 7: OfflinePackDownloadButton 离线下载

### 设计

在 `WikiToolPanel` 的 Export tab（或独立 tab）中添加"下载离线包"按钮。

**交互**：
1. 点击按钮
2. 调用 `GET /api/v1/wiki/{repository}/offline-pack?business_id=...`
3. 将 JSON 响应转为 Blob → 触发浏览器下载（`{repository}-wiki-offline.json`）
4. 如果 `truncated: true`，显示提示："数据已截断至 2000 页"

**文件规划**：
- `dashboard/src/components/wiki/OfflinePackDownloadButton.tsx` (新建)
- `dashboard/src/components/wiki/WikiToolPanel.tsx` (修改：集成按钮)

---

## Task 8: 前端测试覆盖 → 70%

### 策略

1. 新组件（Task 4-7）全部编写 Vitest + RTL 测试
2. 扫描现有组件 `__tests__/` 覆盖缺口，重点补充：
   - `WikiContent` 编辑模式切换
   - `WikiToolPanel` tab 交互
   - `useWikiTree` hook 参数传递
3. 目标：`vitest --coverage` lines ≥ 70%

---

## 依赖

- `pnpm add @uiw/react-codemirror @codemirror/lang-markdown` (Task 4)
- 无其他新依赖

## 测试计划

- [ ] Task 4: WikiEditor 渲染/保存/冲突提示测试
- [ ] Task 5: ReasoningPathPanel 空/有数据/折叠展开测试
- [ ] Task 6: WikiTierSelector 切换/URL 参数/tree API 调用测试
- [ ] Task 7: OfflinePackDownloadButton 下载触发/截断提示测试
- [ ] Task 8: `pnpm test --coverage` ≥ 70% lines
- [ ] 全量 vitest 通过
