# KB Dev Workflow Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create all templates, scripts, and documentation to integrate knowledge-base-service into business project development workflows (Phase 1 deliverables + Phase 2 docs Rule, as it is a small template that shares the same structure).

**Architecture:** Delivers five artifacts: (1) Cursor Rule for KB-backed coding (Phase 1), (2) Cursor Rule for KB-backed doc maintenance (Phase 2, included here since it is a lightweight template), (3) MCP config template, (4) batch indexing script, (5) onboarding guide. All are templates/docs in the knowledge-base-service repo that business teams copy into their projects.

**Tech Stack:** Bash (indexing script), Markdown (docs/rules), JSON (MCP config)

**Spec:** `docs/superpowers/specs/2026-03-27-kb-dev-workflow-integration-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `docs/templates/knowledge-base-coding.mdc` | Cursor Rule: 编码时自动查询 KB |
| Create | `docs/templates/knowledge-base-docs.mdc` | Cursor Rule: 文档维护时查询 KB |
| Create | `docs/templates/mcp-config.json` | Cursor MCP 配置模板 |
| Create | `scripts/index-services.sh` | 批量索引 ultron 服务脚本 |
| Create | `docs/ONBOARDING.md` | 业务项目接入指南 |

---

## Task 1: Cursor Rule — 编码时查询 KB

**Files:**
- Create: `docs/templates/knowledge-base-coding.mdc`

- [ ] **Step 1: Create the Cursor Rule file**

```markdown
---
description: 跨服务业务代码编写时，优先通过知识库 MCP 获取真实代码上下文，减少幻觉
globs:
  - "**/*.java"
  - "**/*.py"
  - "**/*.go"
  - "**/*.ts"
  - "**/*.js"
alwaysApply: true
---

# 知识库优先原则 (Knowledge-Base-First)

你可以通过 MCP 工具 `knowledge-base` 访问项目的代码知识图谱。
在编写或修改涉及跨服务/跨模块调用的代码时，**必须先查询知识库**再动手写代码。

## 核心规则

1. **禁止臆造 API**：当你不确定某个类、方法、接口的签名/参数/返回值时，
   **必须**先调用 `rag_query` 或 `rag_graph` 查询真实定义，不得凭记忆或猜测编写。

2. **跨服务调用前查询**：涉及 RPC 调用、HTTP 接口调用、消息队列消费等跨服务交互时，
   先用 `rag_query` 搜索目标服务的接口定义和文档。

3. **类继承 / 接口实现前查询**：在继承基类或实现接口之前，
   用 `rag_graph`（`inheritance_tree` 或 `class_methods`）确认父类/接口的完整签名。

4. **复杂逻辑修改前查询调用链**：修改公共方法时，
   先用 `rag_graph`（`call_chain`, `direction: upstream`）了解哪些调用方会受影响。

## 查询策略

| 场景 | 推荐方式 |
|------|----------|
| 知道确切的类名/方法名（如 EsClient#insert） | `rag_query`: 传入 FQN 字符串 |
| 知道功能描述但不确定实现位置 | `rag_query`: 用自然语言描述 |
| 需要了解调用链和影响范围 | `rag_graph`: call_chain + upstream/downstream |
| 需要查看文档说明 | `rag_query`: 搜索关键词，返回 Document 类型结果 |

## 降级策略

如果知识库服务不可用（超时或错误），退回常规开发模式，不阻塞编码。
```

Write this content to `docs/templates/knowledge-base-coding.mdc`.

- [ ] **Step 2: Verify the file**

Run: `head -5 docs/templates/knowledge-base-coding.mdc`
Expected: YAML frontmatter with `description` and `globs`

- [ ] **Step 3: Commit**

```bash
git add docs/templates/knowledge-base-coding.mdc
git commit -m "feat: add Cursor Rule template for KB-backed coding"
```

---

## Task 2: Cursor Rule — 文档维护时查询 KB

**Files:**
- Create: `docs/templates/knowledge-base-docs.mdc`

- [ ] **Step 1: Create the docs Cursor Rule file**

```markdown
---
description: 使用知识库 MCP 辅助编写和维护项目文档，确保文档与代码一致
globs:
  - "**/*.md"
  - "**/*.rst"
alwaysApply: true
---

# 文档维护规范 (Documentation Maintenance with Knowledge Base)

你可以通过 MCP 工具 `knowledge-base` 访问项目的代码知识图谱和已有文档。
在编写或更新文档时，**必须先查询知识库获取真实代码信息**，确保文档内容准确。

## 核心规则

1. **文档中的所有代码引用必须来自知识库查询结果**
   写类名、方法签名、参数类型前，先用 `rag_query` 或 `rag_graph(find_entity)` 确认真实定义。

2. **写文档前先搜索已有文档**
   用 `rag_query("目标功能关键词")` 检查是否已有相关文档，避免重复编写或内容冲突。

3. **调用链和依赖关系使用图查询获取**
   不要凭直觉画调用流程图。用 `rag_graph(call_chain)` 获取真实调用链后再画图。

4. **编写完成后验证 + 索引**
   - 用 `rag_query` 搜索文档中提到的每个关键类/方法名，确认它们在代码中真实存在
   - 完成后用 `rag_index(mode="incremental")` 将新文档索引到知识库
```

Write this content to `docs/templates/knowledge-base-docs.mdc`.

- [ ] **Step 2: Verify the file**

Run: `head -5 docs/templates/knowledge-base-docs.mdc`
Expected: YAML frontmatter with globs for `**/*.md` and `**/*.rst`

- [ ] **Step 3: Commit**

```bash
git add docs/templates/knowledge-base-docs.mdc
git commit -m "feat: add Cursor Rule template for KB-backed doc maintenance"
```

---

## Task 3: MCP 配置模板

**Files:**
- Create: `docs/templates/mcp-config.json`

- [ ] **Step 1: Create the MCP config template**

```json
{
  "mcpServers": {
    "knowledge-base": {
      "url": "http://localhost:8100/api/v1/mcp",
      "headers": {
        "Authorization": "Bearer <your-api-token>"
      }
    }
  }
}
```

Write this to `docs/templates/mcp-config.json`.

- [ ] **Step 2: Validate JSON syntax**

Run: `python3 -c "import json; json.load(open('docs/templates/mcp-config.json'))"`
Expected: No error

- [ ] **Step 3: Commit**

```bash
git add docs/templates/mcp-config.json
git commit -m "feat: add MCP config template for KB integration"
```

---

## Task 4: 批量索引脚本

**Files:**
- Create: `scripts/index-services.sh`

- [ ] **Step 1: Create the script with argument parsing and help**

Create `scripts/index-services.sh` with this content:

```bash
#!/bin/bash
set -euo pipefail

KB_URL="${KB_URL:-http://localhost:8100}"
KB_TOKEN="${KB_TOKEN:-}"
BASE_DIR="${BASE_DIR:-}"
MODE="full"
DRY_RUN=false
FAILED=0

DEFAULT_SERVICES=(
  ultron-activity ultron-api ultron-basic ultron-room
  ultron-doc
)

usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS] [SERVICE ...]

Batch index ultron services into knowledge-base-service.

Options:
  --base-dir DIR    Base directory containing service repos (required)
  --kb-url URL      KB service URL (default: \$KB_URL or http://localhost:8100)
  --kb-token TOKEN  API token with editor+ role (default: \$KB_TOKEN)
  --mode MODE       Index mode: full or incremental (default: full)
  --dry-run         Print curl commands without executing
  -h, --help        Show this help

If no SERVICE arguments given, defaults to: ${DEFAULT_SERVICES[*]}

Examples:
  $(basename "$0") --base-dir /opt/ultron --kb-token sk-admin-xxx
  $(basename "$0") --base-dir /opt/ultron --mode incremental ultron-room ultron-api
  $(basename "$0") --dry-run --base-dir /opt/ultron
EOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-dir)  BASE_DIR="$2"; shift 2 ;;
    --kb-url)    KB_URL="$2"; shift 2 ;;
    --kb-token)  KB_TOKEN="$2"; shift 2 ;;
    --mode)      MODE="$2"; shift 2 ;;
    --dry-run)   DRY_RUN=true; shift ;;
    -h|--help)   usage ;;
    -*)          echo "Unknown option: $1" >&2; usage ;;
    *)           break ;;
  esac
done

if [[ -z "$BASE_DIR" ]]; then
  echo "Error: --base-dir is required" >&2
  exit 1
fi

if [[ -z "$KB_TOKEN" ]]; then
  echo "Error: --kb-token is required (or set KB_TOKEN env var)" >&2
  exit 1
fi

SERVICES=("${@:-${DEFAULT_SERVICES[@]}}")

index_service() {
  local svc="$1"
  local dir="$BASE_DIR/$svc"
  local payload="{\"directory\": \"$dir\", \"mode\": \"$MODE\", \"repository\": \"$svc\"}"

  echo "[$svc] Indexing ($MODE)..."

  if [[ "$DRY_RUN" == true ]]; then
    echo "  [DRY-RUN] curl -s -X POST '$KB_URL/api/v1/index' \\"
    echo "    -H 'Content-Type: application/json' \\"
    echo "    -H 'Authorization: Bearer ***' \\"
    echo "    -d '$payload'"
    return 0
  fi

  if [[ ! -d "$dir" ]]; then
    echo "  [WARN] Directory not found: $dir — skipping"
    return 0
  fi

  local response
  response=$(curl -s -w "\n%{http_code}" -X POST "$KB_URL/api/v1/index" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $KB_TOKEN" \
    -d "$payload")

  local http_code
  http_code=$(echo "$response" | tail -1)
  local body
  body=$(echo "$response" | head -n -1)

  if [[ "$http_code" -ge 200 && "$http_code" -lt 300 ]]; then
    echo "  [OK] $body"
  else
    echo "  [FAIL] HTTP $http_code: $body" >&2
    FAILED=$((FAILED + 1))
  fi
}

echo "=== KB Batch Indexer ==="
echo "KB URL: $KB_URL"
echo "Base dir: $BASE_DIR"
echo "Mode: $MODE"
echo "Services: ${SERVICES[*]}"
echo "========================"
echo ""

for svc in "${SERVICES[@]}"; do
  index_service "$svc"
  echo ""
done

if [[ "$FAILED" -gt 0 ]]; then
  echo "DONE with $FAILED failure(s)"
  exit 1
else
  echo "DONE — all services indexed successfully"
fi
```

Write this to `scripts/index-services.sh` and make it executable: `chmod +x scripts/index-services.sh`.

- [ ] **Step 2: Verify script syntax**

Run: `bash -n scripts/index-services.sh`
Expected: No syntax errors

- [ ] **Step 3: Test dry-run mode**

Run: `bash scripts/index-services.sh --dry-run --base-dir /tmp --kb-token test-token`
Expected: Prints curl commands for each default service without executing

- [ ] **Step 4: Test help output**

Run: `bash scripts/index-services.sh --help`
Expected: Usage text with options and examples

- [ ] **Step 5: Commit**

```bash
git add scripts/index-services.sh
git commit -m "feat: add batch indexing script for ultron services"
```

---

## Task 5: 业务项目接入指南 (ONBOARDING.md)

**Files:**
- Create: `docs/ONBOARDING.md`

- [ ] **Step 1: Create the onboarding guide**

Write `docs/ONBOARDING.md` with the following sections:

1. **概述** — 知识库服务简介（1-2 句），适用场景
2. **前置条件**
   - 知识库服务地址（默认 `http://localhost:8100`，生产环境地址由管理员提供）
   - Token 申请：联系管理员获取 editor 角色的 API Token
   - 确认你的仓库已被索引（通过 Dashboard 或 `GET /api/v1/repositories` 检查）
3. **Step 1: 索引你的仓库**
   - 如未索引，使用 `scripts/index-services.sh` 或 Dashboard 触发全量索引
   - 验证：`curl http://kb-service:8100/api/v1/stats?repository=<your-repo>`
4. **Step 2: 配置 Cursor MCP**
   - 复制 `docs/templates/mcp-config.json` 到项目 `.cursor/mcp.json`
   - 修改 `url` 和 `Authorization` 中的 token
5. **Step 3: 安装 Cursor Rules**
   - 复制 `docs/templates/knowledge-base-coding.mdc` 到 `.cursor/rules/`
   - （可选）复制 `docs/templates/knowledge-base-docs.mdc`
6. **Step 4: 验证接入**
   - 在 Cursor 中打开一个代码文件，要求 Agent 查询某个跨服务接口
   - 确认 Agent 调用了 `rag_query` 并返回真实结果
7. **常见问题 (FAQ)**
   - KB 不可用怎么办？— 自动降级
   - 如何更新索引？— 增量索引 / Dashboard Sync
   - 搜索结果不准确？— 检查索引时间，必要时全量重建
8. **最佳实践**
   - 搜索策略优先级表
   - 常见场景 Prompt 示例（3-5 个）

引用 README.md 中已有的 API 示例，避免重复编写。使用相对链接指向 README 和 MCP-INTEGRATION.md。

- [ ] **Step 2: Verify links**

检查文档中的相对链接是否正确指向存在的文件。

Run: `rg -o '\[[^\]]+\]\(([^)]+)\)' docs/ONBOARDING.md -r '$1' | grep -v '^http' | while read -r path; do [ -f "$path" ] && echo "OK: $path" || echo "MISSING: $path"; done`
Expected: All paths marked OK

- [ ] **Step 3: Commit**

```bash
git add docs/ONBOARDING.md
git commit -m "docs: add business project onboarding guide for KB integration"
```

---

## Task 6: 更新 README.md 文档索引

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add documentation index entry**

在 README.md 的 MCP 工具集成 section 之后，添加新的 section 引用 ONBOARDING.md：

```markdown
## 业务项目接入

> **完整文档**: [docs/ONBOARDING.md](docs/ONBOARDING.md) — 包含配置 Cursor MCP、安装 Rules、验证接入等详细步骤。

快速开始：
1. 确认仓库已索引（Dashboard 查看）
2. 复制 `docs/templates/mcp-config.json` → `.cursor/mcp.json`
3. 复制 `docs/templates/knowledge-base-coding.mdc` → `.cursor/rules/`
4. 在 Cursor 中验证 Agent 可查询知识库
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add onboarding section to README"
```

---

## Task 7: Final Verification

- [ ] **Step 1: Verify all new files exist**

Run:
```bash
ls -la docs/templates/knowledge-base-coding.mdc \
       docs/templates/knowledge-base-docs.mdc \
       docs/templates/mcp-config.json \
       scripts/index-services.sh \
       docs/ONBOARDING.md
```
Expected: All 5 files listed

- [ ] **Step 2: Verify JSON validity**

Run: `python3 -c "import json; json.load(open('docs/templates/mcp-config.json')); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Verify script syntax**

Run: `bash -n scripts/index-services.sh`
Expected: No errors

- [ ] **Step 4: Review git log**

Run: `git log --oneline -6`
Expected: 6 commits matching Tasks 1-6 (coding rule, docs rule, MCP config, index script, ONBOARDING, README update)
