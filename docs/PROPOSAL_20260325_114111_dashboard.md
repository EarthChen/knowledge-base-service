# 提案：知识库 Dashboard

## 背景

当前知识库服务仅提供 REST API，缺乏可视化界面。运维人员和开发者无法直观地查看索引状态、搜索测试、图结构浏览等。需要一个轻量级 Dashboard 来提供这些能力。

## 目标

- 提供一个内嵌的 Web Dashboard，零额外部署成本
- 可视化知识库核心指标（节点/边统计、仓库列表）
- 支持常用操作（语义搜索、图查询、触发索引）
- 简洁现代的 UI，单页应用

## 技术方案

### 架构选型

**方案：FastAPI 内嵌静态文件 + 纯前端 SPA（Vanilla JS + Tailwind CSS CDN）**

理由：
- 零构建步骤，无需 Node.js/pnpm 工具链
- 直接内嵌到现有 FastAPI 应用，无需额外进程
- Tailwind CSS CDN 提供现代化 UI
- 纯 JS 避免框架依赖，体积极小
- 通过 Chart.js CDN 实现图表可视化

### 页面布局

```
┌─────────────────────────────────────────────┐
│  KB Dashboard                    [服务状态] │
├──────────┬──────────────────────────────────┤
│          │                                  │
│ 导航侧栏  │  内容区                           │
│          │                                  │
│ ● 概览   │  ┌──────┐ ┌──────┐ ┌──────┐     │
│ ● 搜索   │  │函数数 │ │类数   │ │文档数│     │
│ ● 图查询  │  └──────┘ └──────┘ └──────┘     │
│ ● 索引   │                                  │
│ ● 仓库   │  ┌────────────────────────┐      │
│          │  │   节点/边分布图表        │      │
│          │  └────────────────────────┘      │
│          │                                  │
└──────────┴──────────────────────────────────┘
```

### 功能模块

| 模块 | 功能 | 调用 API |
|------|------|----------|
| **概览** | 显示节点/边统计卡片 + 分布图表 | `GET /api/v1/stats` |
| **仓库** | 已索引仓库列表 + 各仓库节点数 | `GET /api/v1/repositories` |
| **搜索** | 语义搜索表单 + 结果展示 | `POST /api/v1/search` |
| **图查询** | 选择查询类型 + 参数输入 + 结果 | `POST /api/v1/graph` |
| **索引** | 触发全量/增量索引表单 | `POST /api/v1/index` |

### 文件结构

```
knowledge-base-service/
├── static/
│   ├── index.html        # SPA 入口（含所有页面）
│   ├── style.css         # 自定义样式补充
│   └── app.js            # 应用逻辑（路由、API 调用、渲染）
├── main.py               # 新增 StaticFiles mount
```

### 实施清单

- [ ] 创建 `static/index.html` — SPA 框架 + Tailwind CDN + Chart.js CDN
- [ ] 创建 `static/app.js` — 前端路由、API 调用、DOM 渲染
- [ ] 创建 `static/style.css` — 自定义样式补充
- [ ] 修改 `main.py` — 挂载 StaticFiles + 根路由重定向到 Dashboard
- [ ] 更新 `Dockerfile` — 确保 static 目录被包含
- [ ] 更新 README.md — 添加 Dashboard 使用说明
- [ ] 重新构建 Docker 并验证

## 审阅要点

1. **零依赖**：不引入任何 npm/pnpm 构建步骤，纯静态文件
2. **内嵌部署**：直接集成在 FastAPI 中，访问 `http://localhost:8100/` 即可
3. **API 复用**：所有功能均复用现有 REST API，不新增后端逻辑
4. **安全性**：Dashboard 受现有 API_TOKEN 认证保护
5. **Docker 兼容**：Dockerfile 的 `COPY . .` 已自然包含 static 目录
