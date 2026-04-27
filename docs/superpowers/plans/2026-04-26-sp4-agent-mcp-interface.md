# SP4: Agent/MCP Interface Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose wiki knowledge as MCP tools for AI coding agents, with compact knowledge format and auto-generated AGENTS.md.

**Architecture:** New MCP server module exposing 5 tools (wiki_search, wiki_explain, wiki_navigate, wiki_qa, wiki_impact). Supports stdio (local agent) and HTTP/SSE (remote) transports. Compact mode returns structured JSON optimized for LLM context windows.

**Tech Stack:** Python 3.12+, MCP SDK (mcp), FastAPI, pytest

---

### Task 1: MCP Server Skeleton

**Files:**
- Create: `api/mcp_wiki_server.py`
- Test: `tests/api/test_mcp_wiki_server.py`

- [ ] **Step 1: Write failing test for MCP server initialization**
- [ ] **Step 2: Create MCP server with 5 tool definitions**
- [ ] **Step 3: Implement wiki_search tool (delegates to WikiSearchService)**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

---

### Task 2: wiki_explain Tool

**Files:**
- Modify: `api/mcp_wiki_server.py`
- Create: `wiki/entity_explainer.py`
- Test: `tests/wiki/test_entity_explainer.py`

- [ ] **Step 1: Write failing test for entity explanation**
- [ ] **Step 2: Implement EntityExplainer (fetches entity, relationships, signatures, key facts)**
- [ ] **Step 3: Wire into MCP wiki_explain tool**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

---

### Task 3: Compact Knowledge Format

**Files:**
- Create: `wiki/compact_formatter.py`
- Test: `tests/wiki/test_compact_formatter.py`

- [ ] **Step 1: Write test for compact JSON output with token budget**
- [ ] **Step 2: Implement CompactFormatter (structured JSON, respects max_tokens)**
- [ ] **Step 3: Run tests**
- [ ] **Step 4: Commit**

---

### Task 4: wiki_navigate and wiki_impact Tools

**Files:**
- Modify: `api/mcp_wiki_server.py`
- Test: `tests/api/test_mcp_wiki_tools.py`

- [ ] **Step 1: Write tests for navigate (tree browsing) and impact (change analysis)**
- [ ] **Step 2: Implement wiki_navigate (delegates to WikiStore tree methods)**
- [ ] **Step 3: Implement wiki_impact (reuses ChangeDetector from SP3)**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

---

### Task 5: AGENTS.md Auto-Generation

**Files:**
- Create: `wiki/agents_md_generator.py`
- Test: `tests/wiki/test_agents_md_generator.py`

- [ ] **Step 1: Write failing test for AGENTS.md content generation**
- [ ] **Step 2: Implement AgentsMdGenerator (reads wiki metadata, generates markdown)**
- [ ] **Step 3: Hook into wiki generation completion (post-generate event)**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

---

### Task 6: MCP Server Registration and Feature Flag

**Files:**
- Modify: `config.py` (add `mcp_server_enabled` to WikiConfig)
- Modify: `main.py` (register MCP server if enabled)

- [ ] **Step 1: Add feature flag to WikiConfig**
- [ ] **Step 2: Conditionally start MCP server in lifespan**
- [ ] **Step 3: Write integration test**
- [ ] **Step 4: Commit**
