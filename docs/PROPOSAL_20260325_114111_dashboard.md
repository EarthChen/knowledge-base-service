# 提案：知识库 Dashboard

> **状态**: ✅ 已完成（V2 React 版本）
> **最后更新**: 2026-03-25

## 背景

当前知识库服务仅提供 REST API，缺乏可视化界面。运维人员和开发者无法直观地查看索引状态、搜索测试、图结构浏览等。需要一个轻量级 Dashboard 来提供这些能力。

## 目标

- 提供一个内嵌的 Web Dashboard，零额外部署成本
- 可视化知识库核心指标（节点/边统计、仓库列表）
- 支持常用操作（语义搜索、混合搜索、图查询、触发索引）
- 简洁现代的 UI，单页应用
- 支持中英文多语言

## 技术方案

### V1 → V2 演进

| 维度 | V1 (已废弃) | V2 (当前) |
|------|-------------|-----------|
| 框架 | Vanilla JS | React 19 + TypeScript |
| 构建 | 零构建 (CDN) | Vite 8 + pnpm |
| 样式 | Tailwind CDN | Tailwind CSS 4 (PostCSS) |
| 图表 | Chart.js CDN | react-chartjs-2 |
| 状态管理 | 手动 DOM | TanStack Query |
| 路由 | 手动 hash | React Router 7 |
| 国际化 | 无 | 自定义 Context (en/zh) |
| 图标 | SVG 内联 | Lucide React |

### 架构

```
dashboard/              # React 源码
├── src/
│   ├── api/           # API client + React Query hooks
│   ├── components/    # 通用组件 (Layout, StatCard, Toast...)
│   ├── i18n/          # 多语言 (en.ts, zh.ts, context.tsx)
│   └── pages/         # 6个页面组件
├── vite.config.ts     # 构建配置 (输出到 ../static/)
└── package.json

static/                # 构建产物 (由 FastAPI StaticFiles 服务)
├── index.html
└── assets/
    ├── index-*.css
    └── index-*.js
```

### 功能模块

| 模块 | 功能 | 调用 API | 状态 |
|------|------|----------|------|
| **概览** | 统计卡片 + 环形图 + 柱状图 + 边计数 | `GET /api/v1/stats` | ✅ |
| **搜索** | 语义搜索 + 混合搜索，类型过滤 | `POST /api/v1/search`, `/hybrid` | ✅ |
| **图查询** | 9种查询类型动态表单 + JSON 结果 | `POST /api/v1/graph` | ✅ |
| **仓库管理** | 列表 + 删除 + Toast 通知 | `GET /repositories`, `DELETE /index/{repo}` | ✅ |
| **索引** | 全量/增量模式 + 结果展示 | `POST /api/v1/index` | ✅ |
| **设置** | 语言切换 + API Token + 服务信息 | `GET /api/v1/health` | ✅ |

### 多语言支持

- 基于 React Context 的轻量级 i18n 方案
- 支持 `en` (English) 和 `zh` (简体中文)
- 自动检测浏览器语言偏好
- 语言选择持久化到 localStorage
- 所有 UI 文本均已国际化

### 实施清单

- [x] 创建 React + TypeScript 项目 (Vite + pnpm)
- [x] 实现 API client 和 React Query hooks
- [x] 实现 Layout 组件 (侧边栏 + 响应式)
- [x] 实现 Overview 页面 (统计 + 图表)
- [x] 实现 Search 页面 (语义 + 混合搜索)
- [x] 实现 Graph Query 页面 (9种查询类型)
- [x] 实现 Repositories 页面 (列表 + 删除)
- [x] 实现 Indexing 页面 (全量/增量)
- [x] 实现 Settings 页面 (Token + 服务信息)
- [x] 实现 Toast 通知系统
- [x] 实现骨架屏加载动画
- [x] 添加中英文多语言支持
- [x] 修改 `main.py` — SPA fallback 路由
- [x] 创建 `dev.sh` 一键启动脚本
- [x] 更新 `.gitignore`
- [x] 更新 README.md

## 开发指南

```bash
# 开发模式 (HMR)
cd dashboard && pnpm dev      # http://localhost:5173

# 构建生产版本
cd dashboard && pnpm build    # 输出到 ../static/

# 一键启动全部服务
./dev.sh                      # FalkorDB + Backend + Frontend
```
