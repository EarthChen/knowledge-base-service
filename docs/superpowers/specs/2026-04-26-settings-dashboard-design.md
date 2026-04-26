# Settings Dashboard + Code Quality Optimization Design

> Created: 2026-04-26  
> Status: Draft → Pending Approval

## 1. Overview

Add a full-featured Settings page to the Dashboard for managing all system configuration, and fix review issues (P2-P6) from the Wiki frontend redesign.

### Goals
1. All `config.py` settings manageable from Dashboard
2. SQLite persistence layer with env override support
3. Sensitive values encrypted at rest, masked in UI
4. Fix i18n gaps, code quality issues, and performance optimizations

### Non-Goals
- Runtime hot-reload of FalkorDB/Embedding connections (requires restart)
- Multi-tenant settings isolation (single-instance scope)
- Audit log for configuration changes (future iteration)

---

## 2. Architecture

```
Priority: SQLite DB > Environment Variables > Code Defaults

┌─ Dashboard ─────────────────────┐
│  Settings Page                  │
│  ├─ useSettings() hook          │
│  ├─ useUpdateSettings() hook    │
│  └─ 7 SettingsCard components   │
└───────────┬─────────────────────┘
            │ REST API
┌───────────▼─────────────────────┐
│  api/routes/settings_routes.py  │
│  ├─ GET  /api/v1/settings       │
│  ├─ GET  /api/v1/settings/{cat} │
│  ├─ PUT  /api/v1/settings       │
│  └─ POST /api/v1/settings/test  │
└───────────┬─────────────────────┘
            │
┌───────────▼─────────────────────┐
│  services/settings_service.py   │
│  ├─ merge(db, env, defaults)    │
│  ├─ mask_secrets()              │
│  └─ encrypt/decrypt secrets     │
└───────────┬─────────────────────┘
            │
┌───────────▼─────────────────────┐
│  store/settings_store.py        │
│  SQLite: data/kb_settings.db    │
│  Table: settings(key, value,    │
│         category, updated_at)   │
└─────────────────────────────────┘
```

---

## 3. Backend Design

### 3.1 SQLite Settings Store

File: `store/settings_store.py`

```python
class SettingsStore:
    def __init__(self, db_path: str = "data/kb_settings.db"):
        ...
    async def get_all(self) -> dict[str, dict[str, str]]:
        """Return all settings grouped by category."""
    async def get_by_category(self, category: str) -> dict[str, str]:
        """Return settings for a single category."""
    async def upsert(self, key: str, value: str, category: str) -> None:
        """Insert or update a setting."""
    async def upsert_batch(self, items: list[dict]) -> None:
        """Batch upsert settings."""
    async def delete(self, key: str) -> None:
        """Remove a setting (reverts to env/default)."""
```

Schema:
```sql
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'system',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_settings_category ON settings(category);
```

### 3.2 Settings Service

File: `services/settings_service.py`

Responsibilities:
- Merge three layers: `DB overrides > env vars > pydantic defaults`
- Encrypt sensitive values before storage (Fernet symmetric encryption)
- Mask sensitive values in read responses (`sk-abc...xyz` → `sk-ab***yz`)
- Validate values before persisting

Sensitive keys (encrypted in DB, masked in GET responses):
- `falkordb.password`
- `llm.api_key`
- `git.gitlab_token`
- `git.github_token`
- `wiki.git_token`
- `api_token`

Encryption key: Derived from `SETTINGS_ENCRYPTION_KEY` env var (or auto-generated and stored in `data/.settings_key`).

### 3.3 Settings API

File: `api/routes/settings_routes.py`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/v1/settings` | ADMIN | All settings (masked secrets) |
| GET | `/api/v1/settings/{category}` | ADMIN | Category settings |
| PUT | `/api/v1/settings` | ADMIN | Batch update |
| PUT | `/api/v1/settings/{key}` | ADMIN | Single update |
| DELETE | `/api/v1/settings/{key}` | ADMIN | Revert to default |
| POST | `/api/v1/settings/test-connection` | ADMIN | Test FalkorDB/LLM connection |

Request body for PUT:
```json
{
  "settings": [
    {"key": "wiki.coverage_report_enabled", "value": "true", "category": "wiki_features"},
    {"key": "llm.api_key", "value": "sk-new-key", "category": "llm"}
  ]
}
```

Response for GET:
```json
{
  "categories": {
    "wiki_features": {
      "wiki.coverage_report_enabled": {"value": "true", "source": "db", "sensitive": false},
      "wiki.stale_detection_enabled": {"value": "true", "source": "env", "sensitive": false}
    },
    "llm": {
      "llm.api_key": {"value": "sk-ab***yz", "source": "db", "sensitive": true},
      "llm.model": {"value": "gpt-4o-mini", "source": "default", "sensitive": false}
    }
  }
}
```

### 3.4 Configuration Categories

| Category | Key Prefix | Settings Count | Notes |
|----------|-----------|----------------|-------|
| `wiki_features` | `wiki.*` (flags) | ~10 | Toggle switches |
| `wiki_generation` | `wiki.*` (gen) | ~12 | Generation params |
| `wiki_git` | `wiki.git_*` | ~10 | Git publish config |
| `llm` | `llm.*` | ~10 | LLM provider config |
| `storage` | `falkordb.*` | ~4 | Graph database |
| `embedding` | `embedding.*` | ~8 | Embedding model |
| `system` | `host`, `port`, etc. | ~8 | System-level |

### 3.5 Settings-Config Bridge

Modify `config.py` `get_settings()` to optionally load DB overrides:

```python
@lru_cache
def get_settings() -> Settings:
    base = Settings()
    # Merge DB overrides if available
    try:
        from store.settings_store import SettingsStore
        store = SettingsStore()
        overrides = store.get_all_sync()
        return _apply_overrides(base, overrides)
    except Exception:
        return base
```

---

## 4. Frontend Design

### 4.1 New Files

| File | Type | Description |
|------|------|-------------|
| `src/pages/SettingsPage.tsx` | Page | Main settings page with tabs |
| `src/hooks/useSettings.ts` | Hook | Fetch settings by category |
| `src/hooks/useUpdateSettings.ts` | Hook | Mutation for updating settings |
| `src/components/settings/SettingsCard.tsx` | Component | Generic card wrapper |
| `src/components/settings/SettingsToggle.tsx` | Component | Boolean toggle |
| `src/components/settings/SettingsInput.tsx` | Component | Text/number input |
| `src/components/settings/SettingsSelect.tsx` | Component | Dropdown select |
| `src/components/settings/SettingsSecretInput.tsx` | Component | Password input with reveal |
| `src/components/settings/SettingsSlider.tsx` | Component | Range slider |
| `src/components/settings/WikiFeaturesCard.tsx` | Card | Wiki feature toggles |
| `src/components/settings/WikiGenerationCard.tsx` | Card | Wiki generation params |
| `src/components/settings/WikiGitCard.tsx` | Card | Git integration |
| `src/components/settings/LLMConfigCard.tsx` | Card | LLM provider settings |
| `src/components/settings/StorageConfigCard.tsx` | Card | FalkorDB settings |
| `src/components/settings/EmbeddingConfigCard.tsx` | Card | Embedding model |
| `src/components/settings/SystemConfigCard.tsx` | Card | System settings |

### 4.2 Settings Page Layout

Tab-based layout with sidebar navigation:

```
┌─────────────────────────────────────────┐
│ ⚙ Settings                              │
├──────────┬──────────────────────────────┤
│ Wiki     │ [WikiFeaturesCard]           │
│ ├ Features│                             │
│ ├ Generation│ [WikiGenerationCard]      │
│ ├ Git    │                              │
│ LLM      │ [LLMConfigCard]             │
│ Storage   │ [StorageConfigCard]         │
│ Embedding │ [EmbeddingConfigCard]       │
│ System    │ [SystemConfigCard]          │
└──────────┴──────────────────────────────┘
```

### 4.3 Settings Types

```typescript
type SettingSource = "db" | "env" | "default";

type SettingItem = {
  value: string;
  source: SettingSource;
  sensitive: boolean;
};

type SettingsCategory = Record<string, SettingItem>;
type SettingsResponse = {
  categories: Record<string, SettingsCategory>;
};

type SettingUpdate = {
  key: string;
  value: string;
  category: string;
};
```

### 4.4 Route

Add to `App.tsx`:
```tsx
<Route path="settings" element={<SettingsPage />} />
```

Add settings link to the sidebar navigation.

---

## 5. Review Issues Fix (P2-P6)

### P2: i18n Completion

Extract all hardcoded English strings in Phase 8-11 components to i18n:

| Component | Strings to extract |
|-----------|--------------------|
| WikiEditButton | "Edit on Git" |
| WikiAnnotationLayer | "Add annotation", "Write a comment...", "Cancel", "Add" |
| WikiAnnotationSidebar | "No annotations yet. Select text to add one." |
| WikiVersionHistory | "No version history available", "Updated", "Diff" |
| WikiDiffViewer | "Unable to load diff" |
| WikiUpdateNotification | "has been updated", "Refresh" |
| WikiGenerationProgress | "in progress...", "completed", "failed" |
| WikiBusinessExportPanel | All labels |
| GitPushConfigDialog | All labels |
| WikiSuggestedQuestions | "Explore further" |

### P3: Code Quality

1. **Extract shared `getErrorMessage`** → `src/utils/errorUtils.ts`
2. **Unify `repository` vs `businessId`** in WikiLintPanel, GraphInsightsPanel
3. **Remove duplicate wikiHref** check across files

### P4: Performance

1. **TreeBranch React.memo** — Memoize to avoid full-tree re-render on expand/collapse
2. **WikiLinkPreview lazy fetch** — Only enable query after hover timer fires, not on mount
3. **CoverageCard chartData useMemo** — Memoize chart configuration
4. **SearchBar mutation cancel** — Cancel previous mutation on new search

### P5: Accessibility

1. **Tree nav ARIA** — `role="tablist"` on view switcher, `role="tab"` on buttons
2. **Search combobox** — `role="combobox"` on input, `aria-controls`, arrow key nav
3. **References panel responsive** — Show as bottom sheet on mobile

---

## 6. Implementation Phases

| Phase | Scope | Effort |
|-------|-------|--------|
| S-Phase 1 | Backend: SQLite store + Settings service + Encryption | Medium |
| S-Phase 2 | Backend: Settings API + Config bridge | Medium |
| S-Phase 3 | Frontend: Settings types + hooks + generic components | Medium |
| S-Phase 4 | Frontend: 7 Settings cards + page + route | Large |
| S-Phase 5 | i18n extraction (P2) | Small |
| S-Phase 6 | Code quality fixes (P3) + Performance (P4) + A11y (P5) | Medium |
| S-Phase 7 | Tests for all new components and backend | Medium |
