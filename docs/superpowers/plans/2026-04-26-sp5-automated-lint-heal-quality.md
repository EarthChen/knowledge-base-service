# SP5: Automated Lint/Heal + Quality Loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate wiki quality maintenance through scheduled lint, auto-heal actions, Memory Loop injection into generation, and user feedback integration.

**Architecture:** LintScheduler runs periodically (default 6h) using existing WikiLintService. Auto-heal actions queue incremental regeneration for stale pages. MemoryLoop.inject_into_generation() is called during WikiComposer.compose_page(). User feedback stored as WikiFeedback graph nodes.

**Tech Stack:** Python 3.12+, FastAPI, FalkorDB, asyncio, pytest

---

### Task 1: LintScheduler Background Worker

**Files:**
- Create: `wiki/lint_scheduler.py`
- Modify: `main.py` (register in lifespan)
- Test: `tests/wiki/test_lint_scheduler.py`

- [ ] **Step 1: Write failing test for scheduler execution**
- [ ] **Step 2: Implement LintScheduler (asyncio.Task-based, configurable interval)**
- [ ] **Step 3: Wire into lifespan alongside SyncScheduler**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

---

### Task 2: Auto-Heal Actions

**Files:**
- Create: `wiki/auto_healer.py`
- Test: `tests/wiki/test_auto_healer.py`

- [ ] **Step 1: Write tests for each auto-heal action (stale→regenerate, orphan→deprecate, broken ref→remove)**
- [ ] **Step 2: Implement AutoHealer with action handlers**
- [ ] **Step 3: Integrate with LintScheduler (run auto-heal after lint)**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

---

### Task 3: Memory Loop Generation Injection

**Files:**
- Modify: `wiki/composer.py` (accept optional MemoryLoop in constructor)
- Modify: `wiki/service.py` (pass MemoryLoop to WikiComposer)
- Test: `tests/wiki/test_memory_injection.py`

- [ ] **Step 1: Write failing test**

```python
# tests/wiki/test_memory_injection.py
import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_composer_injects_memories():
    """WikiComposer should call memory_loop.inject_into_generation when memory_loop is provided."""
    mock_memory = AsyncMock()
    mock_memory.inject_into_generation.return_value = "enriched context with Q&A"
    # Create WikiComposer with mock memory_loop
    # Call compose_page
    # Assert inject_into_generation was called
    mock_memory.inject_into_generation.assert_not_called()  # placeholder
```

- [ ] **Step 2: Add memory_loop parameter to WikiComposer.__init__**
- [ ] **Step 3: Call inject_into_generation in compose_page before LLM generation**
- [ ] **Step 4: Update WikiService._composer_for to pass memory_loop**
- [ ] **Step 5: Run tests**
- [ ] **Step 6: Commit**

---

### Task 4: User Feedback System — Backend

**Files:**
- Create: `store/wiki_feedback_store.py`
- Modify: `api/routes/wiki_routes.py` (add feedback endpoints)
- Test: `tests/wiki/test_feedback.py`

- [ ] **Step 1: Write failing test for feedback persistence**
- [ ] **Step 2: Implement WikiFeedbackStoreMixin (persist, aggregate)**
- [ ] **Step 3: Add POST /api/v1/wiki/pages/{page_uid}/feedback endpoint**
- [ ] **Step 4: Add GET /api/v1/wiki/feedback/summary endpoint**
- [ ] **Step 5: Run tests**
- [ ] **Step 6: Commit**

---

### Task 5: User Feedback System — Frontend

**Files:**
- Create: `dashboard/src/components/wiki/WikiPageFeedback.tsx`
- Modify: `dashboard/src/components/wiki/WikiContent.tsx`
- Test: `dashboard/src/components/wiki/__tests__/WikiPageFeedback.test.tsx`

- [ ] **Step 1: Write failing test for feedback component**
- [ ] **Step 2: Implement WikiPageFeedback (thumbs up/down + optional comment)**
- [ ] **Step 3: Add to WikiContent footer**
- [ ] **Step 4: Run tests**
- [ ] **Step 5: Commit**

---

### Task 6: Feature Flags and Config

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add lint_scheduler_enabled, feedback_enabled to WikiConfig**
- [ ] **Step 2: Guard all new features behind flags**
- [ ] **Step 3: Commit**
