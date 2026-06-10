# Multi-Version Comparison & Architecture Refinement

## Problem Statement

manhua-workflow 当前每个资产（角色/场景/道具/故事板/视频分段）只有单一版本，用户无法对比不同提示词或生成结果。同时资产状态流转缺乏完整性保障，容易卡在中间态。

核心需求：
1. **多版本对比**：每个资产支持可配置数量（2~4）的版本，包括提示词对比和生成结果对比
2. **状态机完整性**：版本级状态机，防止卡死，支持回退
3. **提示词模板多版本**：同一类型（如故事板）可以有多种模板变体，版本生成时可选用不同模板
4. **前端较大改造**：支持多版本对比交互

## Design

### 1. Data Model: pipeline.json Version Extension

**Current structure** (flat, single version):
```json
"characters": {
  "婉瑜": { "seed": "...", "status": "needed", "draft_prompt": "", "task_id": "" }
}
```

**New structure** (multi-version with version array):
```json
"characters": {
  "婉瑜": {
    "seed": "...",
    "version_count": 2,
    "selected_version": null,
    "versions": [
      {
        "id": 0,
        "draft_prompt": "",
        "status": "needed",
        "task_id": null,
        "result_url": null,
        "template_variant": "default"
      },
      {
        "id": 1,
        "draft_prompt": "",
        "status": "needed",
        "task_id": null,
        "result_url": null,
        "template_variant": "variant_a"
      }
    ]
  }
}
```

**Field definitions**:
- `version_count`: configurable 2~4, set at parse/creation time
- `selected_version`: id of the user-adopted version, `null` means not selected
- `versions[].id`: integer, 0-indexed
- `versions[].template_variant`: which prompt template variant was used to generate this version's prompt
- `versions[].status`: per-version state machine value
- `versions[].task_id`: API task ID for this version's generation
- `versions[].result_url`: local path to generated result

**Applied to all asset types**:
- `assets.characters`, `assets.scenes`, `assets.props`: same structure
- `storyboards.*.board_versions[]`: storyboard image versions (replaces `board_status`/`board_task_id`)
- `storyboards.*.video_parts[].video_versions[]`: video segment versions (replaces `video_status`/`video_task_id`)

**Storyboards with versioning**:
```json
"storyboards": {
  "s01_01": {
    "episode": 1,
    "scene_num": 1,
    "script_title": "...",
    "characters_in_scene": ["婉瑜"],
    "scene_location": "...",
    "script_segment": "...",
    "dependency_stale": false,
    "stale_reasons": [],
    "selected_board_version": null,
    "board_versions": [
      { "id": 0, "draft_prompt": "", "status": "needed", "board_task_id": null, "template_variant": "default" },
      { "id": 1, "draft_prompt": "", "status": "needed", "board_task_id": null, "template_variant": "variant_a" }
    ],
    "video_parts": [
      {
        "part": 1,
        "duration": 10,
        "selected_video_version": null,
        "video_versions": [
          { "id": 0, "draft_prompt": "", "status": "needed", "video_task_id": null, "template_variant": "default" },
          { "id": 1, "draft_prompt": "", "status": "needed", "video_task_id": null, "template_variant": "variant_a" }
        ]
      }
    ]
  }
}
```

**Backward compatibility**: when reading old pipeline.json without `versions` field, auto-wrap into single-version format:
```python
def migrate_asset(old_asset: dict) -> dict:
    if "versions" in old_asset:
        return old_asset
    return {
        "seed": old_asset.get("seed", ""),
        "version_count": 1,
        "selected_version": 0 if old_asset.get("status") == "completed" else None,
        "versions": [{
            "id": 0,
            "draft_prompt": old_asset.get("draft_prompt", ""),
            "status": old_asset.get("status", "needed"),
            "task_id": old_asset.get("task_id"),
            "result_url": old_asset.get("result_url"),
            "template_variant": "default",
        }],
    }
```

### 2. Prompt Template Variants

**Current structure** (`prompt_templates.json`): flat key-value
```json
{ "character": "...", "scene": "...", "prop": "...", "storyboard": "...", "video": "..." }
```

**New structure**: each type maps to a dict of named variants
```json
{
  "character": {
    "default": "你是影视角色提示词生成专家...",
    "sketch_style": "生成素描风格角色设定板..."
  },
  "scene": {
    "default": "你是影视场景提示词生成专家..."
  },
  "storyboard": {
    "default": "你是影视故事板提示词生成专家...",
    "action_focus": "生成以动作为核心的故事板...",
    "emotional_focus": "生成以情绪为核心的故事板..."
  },
  "prop": {
    "default": "你是影视道具提示词生成专家..."
  },
  "video": {
    "default": "你是视频提示词生成专家..."
  }
}
```

**Rules**:
- Each type must have a `default` variant (the built-in template)
- Users can add/rename/delete custom variants via API
- Variant names: lowercase alphanumeric + underscore, max 32 chars
- When creating versions in pipeline.json, each version can reference a different `template_variant`
- The `template_variant` field on a version is set at prompt generation time

**API additions**:
- `POST /api/project/prompt-templates/variant` — add a new variant
- `DELETE /api/project/prompt-templates/variant` — delete a variant (cannot delete `default`)
- `PUT /api/project/prompt-templates/variant` — update a variant's content

**Migrate old templates**: when reading old flat format, auto-wrap into `{"default": "..."}`.

### 3. Version State Machine

**States and transitions**:

```
              ┌──────────────────────────────────────┐
              │          (edit prompt)                │
              │◄─────────────────────────────────────┐│
              │                                      ▼│
  needed ──► drafting ──► drafted ──► submitted ──► completed
                                 │                   │
                                 │            (re-submit)│
                                 │                   │
                                 └──────────────► failed
                                              ▲       │
                                              └───────┘ (retry)
```

| Current | Action | Next | Condition |
|---------|--------|------|-----------|
| needed | generate prompt | drafted | LLM returns success |
| needed | manual edit | drafted | user fills content |
| drafted | edit prompt | drafted | stays in drafted |
| drafted | submit | submitted | prompt non-empty |
| submitted | poller detects done | completed | API success |
| submitted | poller detects fail | failed | API failure |
| submitted | poller timeout (>30min) | failed | timeout |
| failed | retry (regenerate prompt) | drafting | user choice |
| failed | retry (re-submit same prompt) | submitted | user choice |
| completed | edit prompt | drafted | user wants revision |
| completed | re-submit | submitted | user wants new result |

**Asset-level derived status** (no stored field):

```python
def derive_asset_status(versions, selected_version):
    if selected_version is not None:
        sv = next((v for v in versions if v["id"] == selected_version), None)
        if sv and sv["status"] == "completed":
            return "completed"
    statuses = {v["status"] for v in versions}
    if statuses == {"needed"}:
        return "needed"
    if "submitted" in statuses:
        return "in_progress"
    if "failed" in statuses and not statuses.intersection({"drafted", "completed"}):
        return "failed"
    return "in_progress"
```

### 4. Version Selection & Downstream Flow

**Selection rules**:
- `selected_version` can only point to a `completed` version
- Selection is idempotent (re-selecting same version is a no-op)
- User can switch selection from one completed version to another

**Downstream auto-flow**:
- When a version is selected, downstream references automatically use that version's result
- e.g., character 婉瑜 selected v2 → storyboards referencing 婉瑜 use v2's image

**Stale marking on switch**:
- When `selected_version` changes, scan all storyboards for `characters_in_scene` containing this asset
- Mark those storyboards `dependency_stale: true`, append to `stale_reasons`
- Similarly, storyboard version switch → mark video_parts as stale
- Stale assets show "needs refresh" in UI
- Re-submitting a stale asset resets `dependency_stale: false`

**API**: `POST /api/project/select-version`

For assets (characters/scenes/props):
```json
{
  "project_name": "...",
  "category": "characters",       // characters|scenes|props
  "name": "婉瑜",
  "version_id": 1
}
```

For storyboard board version:
```json
{
  "project_name": "...",
  "category": "storyboard",
  "scene_key": "s01_01",
  "version_id": 1
}
```

For video part version:
```json
{
  "project_name": "...",
  "category": "video_part",
  "scene_key": "s01_01",
  "part": 1,
  "version_id": 1
}
```

### 5. API Changes Summary

**New endpoints**:
- `POST /api/project/select-version` — select a completed version as the adopted one
- `PUT /api/prompts/update-draft` — update a specific version's draft_prompt
- `POST /api/prompts/add-version` — add a new version to an asset
- `POST /api/project/prompt-templates/variant` — add template variant
- `DELETE /api/project/prompt-templates/variant` — delete template variant
- `PUT /api/project/prompt-templates/variant` — update template variant

**Modified endpoints**:
- `POST /api/prompts/generate` — add `version_id` and `template_variant` fields
- `POST /api/prompts/batch-generate` — same additions per item
- `POST /api/tasks/submit` — add `version_id` field
- `POST /api/tasks/batch-submit` — same addition per item
- `POST /api/tasks/{task_id}/retry` — add `version_id` field
- `GET /api/project/status` — return derived asset-level status + per-version details + `dependency_stale`
- `GET /api/project/prompt-templates` — return new variant dict structure
- `PUT /api/project/prompt-templates` — accept variant dict structure

**Sync principle**: every UI write operation = one API call = one atomic pipeline.json write. Frontend never caches mutable state locally.

### 6. Poller Changes

- Scan `versions[].status == "submitted"` instead of top-level `status`
- Update per-version status/task_id/result_url
- Timeout: mark as `failed` if submitted > 30 min
- Download logic unchanged, just per-version
- After updating, re-derive asset-level status for response

### 7. Chat Agent Changes

- System prompt includes version summaries
- Actions must include `version_id`:
  - `update_draft_prompt` → add `version_id`
  - `submit_task` → add `version_id`
  - `generate_prompt` → add `version_id`, `template_variant`
  - new: `select_version` action
- `_execute_actions` updated to write per-version fields

### 8. Frontend Overview

**Asset detail panel**:
- Show version tabs (v1, v2, v3...) at top of detail panel
- Each tab shows: template variant name, prompt (editable), status badge, result image/video
- "Select this version" button on completed versions (highlights as adopted)
- "Generate prompt" dropdown: pick template variant → generate for this version
- "Submit" button per version
- Side-by-side comparison mode: select 2 versions, show prompts diff + results side by side

**Storyboard panel**:
- Board versions tab (same as asset)
- Video parts: each part has its own version tabs

**Template editor**:
- Per type, show list of variants with add/delete/edit
- Cannot delete `default` variant

**Stale indicator**:
- Yellow banner on storyboard cards: "角色版本已切换，建议重新生成"
- Dismisses on re-submit

### 9. Backward Compatibility

- Old pipeline.json auto-migrated to single-version on read
- Old prompt_templates.json auto-migrated to `{"default": "..."}` on read
- All existing API contracts preserved (new fields are optional with sensible defaults)
- Frontend detects `version_count` and adapts UI accordingly

### 10. Implementation Phases

**Phase 1: Data model & migration**
- Update pipeline.py with migration helpers
- Update prompt template structure
- Ensure all reads go through migration layer

**Phase 2: API layer**
- Add/modify all endpoints listed in section 5
- Update poller for version scanning
- Update status derivation logic

**Phase 3: Chat agent**
- Update system prompt builder for version info
- Update action execution for version_id

**Phase 4: Frontend**
- Version tabs in asset detail panel
- Side-by-side comparison mode
- Template variant editor
- Stale dependency indicators
- Select-version UI

**Phase 5: Testing**
- Migrate old pipeline.json → verify single-version works
- Multi-version generate → submit → poll → select flow
- Version switch → stale marking → re-submit flow
- Template variant CRUD
- Chat agent version-aware actions
