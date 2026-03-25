# Proposal: Token-Business 绑定

**状态**: Implemented
**日期**: 2025-03-25

## 背景

当前权限系统中，Token 和业务（Business）是独立概念：
- `API_TOKENS=admin:sk-xxx,editor:sk-yyy,viewer:sk-zzz`
- 所有请求都需要通过 `X-Business-Id` Header 指定业务上下文

**问题**：对于绑定到特定业务的用户（如 editor/viewer），每次请求都携带 `X-Business-Id` 是多余的，且存在误操作跨业务的风险。

## 目标

- Token 可直接绑定到特定业务，无需每次请求携带 `X-Business-Id`
- 管理员 Token 保持灵活性，通过 `X-Business-Id` 切换业务
- 绑定 Token 访问非绑定业务时，返回 403

## 设计方案

### 1. Token 格式扩展

```
API_TOKENS=role:token[:business_id]
```

示例：
```env
API_TOKENS=admin:sk-admin-001,editor:sk-editor-001:project_a,viewer:sk-viewer-001:project_b
```

- `admin:sk-admin-001` → 管理员，通过 `X-Business-Id` 指定业务（默认 default）
- `editor:sk-editor-001:project_a` → 编辑者，绑定到 `project_a`
- `viewer:sk-viewer-001:project_b` → 观察者，绑定到 `project_b`

### 2. 数据结构变更

```python
@dataclass
class TokenInfo:
    role: Role
    business_id: str | None  # None = 未绑定（管理员可切换）
```

Token 注册表从 `dict[str, Role]` 改为 `dict[str, TokenInfo]`。

### 3. 业务解析逻辑

```
Token 有 business_id 绑定?
  ├─ 是 → 使用绑定的 business_id（忽略 X-Business-Id Header）
  └─ 否 → 使用 X-Business-Id Header（默认 "default"）
```

如果绑定 Token 请求中携带了 `X-Business-Id` 且与绑定值不同，返回 **403 Forbidden**。

### 4. /auth/me 响应增强

```json
{
  "role": "editor",
  "auth_enabled": true,
  "business_id": "project_a"   // 新增: 绑定的业务 ID，null 表示未绑定
}
```

### 5. 前端适配

- `/auth/me` 返回 `business_id` 时，自动设置当前业务，隐藏业务选择器
- 管理员（无绑定）保持业务选择器可见

## 实施清单

- [ ] **Backend: auth.py** — `TokenInfo` 数据类 + 解析 3 段式 Token 格式
- [ ] **Backend: main.py** — `_get_business_id` 依赖注入从 Token 绑定解析业务
- [ ] **Backend: /auth/me** — 响应中增加 `business_id` 字段
- [ ] **Frontend: AuthContext** — 读取 `business_id` 并暴露
- [ ] **Frontend: BusinessContext** — 当 Token 绑定业务时，自动锁定业务选择
- [ ] **Frontend: Layout** — 条件隐藏业务选择器
- [ ] **Docs: MCP-INTEGRATION.md** — 更新 Token 配置说明
- [ ] **Docs: README.md** — 更新认证配置示例

## 向后兼容

- 无 business_id 的 2 段式 Token（`role:token`）行为不变
- 单一 `API_TOKEN`（旧格式）继续作为管理员 Token
- 无 Token 配置时全开放模式不变
