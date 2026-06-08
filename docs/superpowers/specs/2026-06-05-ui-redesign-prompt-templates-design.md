# manhua-workflow UI Redesign + Prompt Template Editor

## Goal

Redesign the manhua-workflow web UI from the current dark purple theme to a clean light-themed professional tool, and add a per-project editable system prompt template feature.

## Scope

- Visual redesign: light color system, Lucide icons, design tokens, spacing/typography normalization
- New feature: editable system prompt templates per project
- No layout restructuring (keep three-column layout)
- No file splitting (stay single HTML file)

## Design Tokens (CSS Variables)

### Colors

```
:root {
  /* Backgrounds */
  --bg-base:        #ffffff;
  --bg-surface:     #f8f9fb;
  --bg-elevated:    #ffffff;
  --bg-muted:       #f1f3f5;

  /* Text */
  --text-primary:   #1a1d23;
  --text-secondary: #6b7280;
  --text-muted:     #9ca3af;
  --text-on-accent: #ffffff;

  /* Accent (indigo) */
  --accent:         #6366f1;
  --accent-hover:   #4f46e5;
  --accent-light:   #eef2ff;
  --accent-muted:   #c7d2fe;

  /* Semantic */
  --success:        #22c55e;
  --success-light:  #f0fdf4;
  --warning:        #f59e0b;
  --warning-light:  #fffbeb;
  --error:          #ef4444;
  --error-light:    #fef2f2;

  /* Borders */
  --border:         #e5e7eb;
  --border-hover:   #d1d5db;
}
```

### Typography

| Token | Size | Usage |
|-------|------|-------|
| --text-xs | 11px | Badges, micro labels |
| --text-sm | 12px | Secondary text, labels |
| --text-base | 14px | Body text |
| --text-md | 16px | Subheadings |
| --text-lg | 18px | Panel titles |
| --text-xl | 20px | Page title |

Line-height: 1.5 for body, 1.3 for headings.

### Spacing (4/8px grid)

```
--space-1: 4px;   --space-2: 8px;   --space-3: 12px;
--space-4: 16px;  --space-5: 20px;  --space-6: 24px;
--space-8: 32px;
```

### Radius / Shadow

```
--radius-sm: 6px;    --radius-md: 8px;    --radius-lg: 12px;
--shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
--shadow-md: 0 2px 8px rgba(0,0,0,0.08);
--shadow-lg: 0 4px 16px rgba(0,0,0,0.12);
```

## Icon System

Replace all emoji icons with Lucide via CDN (`https://unpkg.com/lucide@latest`).

| Current | Lucide | Context |
|---------|--------|---------|
| ✓ | `check` | Completed status |
| ✗ | `x` | Failed status |
| ○ | `circle` | Needed/pending status |
| ... (spinning) | `loader` (CSS rotate) | Submitted/in-progress |
| ⚙ | `settings` | Settings button |
| ✨ | `sparkles` | Assistant FAB |
| □ | `image` | Thumbnail placeholder |

Phase tab icons:
- Characters: `users`
- Scenes: `image`
- Storyboards: `layout-grid`
- Video: `video`
- Templates: `file-text`

Lucide usage: `<i data-lucide="icon-name"></i>` then call `lucide.createIcons()` after DOM updates.

## Component Changes

### Header
- Background: `--bg-surface`, border-bottom: `--border`
- Project name: `--text-primary` + `--accent` highlight
- Progress bar moves from sidebar bottom into header (inline with project name)
- Settings: Lucide `settings` icon

### Sidebar (200px)
- Background: `--bg-elevated`, border-right: `--border`
- Phase tabs: vertical stack, each = Lucide icon + text label
- Selected tab: `--accent-light` background + `--accent` left border
- Scene cards: `--bg-muted` base + `--border`, selected = `--accent-light` + `--accent-muted` left border

### Asset Cards (Grid)
- White `--bg-elevated` + `--border` + `--shadow-sm`
- Hover: `--shadow-md` + `--border-hover`
- Selected: `--accent-light` background + 2px `--accent` left border
- Status badges: completed = `--success` bg + Lucide `check`; submitted = `--warning` bg + `loader`; failed = `--error` bg + Lucide `x`; needed = `--bg-muted` + Lucide `circle`

### Modals
- White `--bg-elevated` + `--shadow-lg` + `--radius-lg`
- Scrim: `rgba(0,0,0,0.3)`

### Agent Panel
- White slide-in drawer, `--shadow-lg` on left edge
- User bubble: `--accent-light` background
- Assistant bubble: `--bg-muted` background

### Empty States
- Centered `--text-muted` text + subtle Lucide icon

## Prompt Template Editor

### Data Model

New file `prompt_templates.json` in each project directory:

```json
{
  "character": "...",
  "scene": "...",
  "prop": "...",
  "storyboard": "...",
  "video": "..."
}
```

Defaults come from the existing constants in `api/routes/prompts.py` (CHARACTER_SYSTEM, SCENE_SYSTEM, PROP_SYSTEM, STORYBOARD_SYSTEM, VIDEO_SYSTEM). On first load, if the file doesn't exist, the backend writes it with default values.

### Backend API

**GET `/api/project/prompt-templates`**
- Query params: `project_path` (absolute path), optional `defaults=true`
- Without `defaults`: reads `prompt_templates.json` from project dir. If missing, creates it from code defaults and returns it.
- With `defaults=true`: returns the hardcoded code defaults (CHARACTER_SYSTEM etc.) without reading/writing any file — used by the "Reset to Default" button.
- Response: `{ "character": "...", "scene": "...", "prop": "...", "storyboard": "...", "video": "..." }`

**PUT `/api/project/prompt-templates`**
- Query param: `project_path`
- Body: `{ "character": "...", "scene": "...", ... }` (partial updates allowed)
- Writes `prompt_templates.json` atomically (use pipeline.py write pattern)
- Response: `{ "ok": true }`

### Integration with prompt generation

In `api/routes/prompts.py`, `generate_prompt_endpoint`:
- After resolving `project_dir`, read `prompt_templates.json`
- Use project template for the corresponding type if available, fall back to code constants
- No change to the function signature or request model

### Frontend UI

New phase tab "Templates" (5th tab) with Lucide `file-text` icon.

Layout in main content area:
- Title: "Prompt Templates"
- Dropdown select: Character / Scene / Prop / Storyboard / Video
- Full-height textarea (monospace font, `--bg-surface` background)
- Button row: "Reset to Default" (secondary) + "Save" (primary)

Interactions:
- On tab enter: fetch templates from API, populate dropdown + textarea
- On dropdown change: switch textarea content
- "Reset to Default": confirm dialog, then overwrite textarea with code defaults (fetched via GET `?defaults=true` on the same endpoint)
- "Save": PUT the current template type's content to API, show success toast

## Implementation Order

1. CSS variables + light theme (replace all hardcoded colors/values)
2. Lucide CDN + icon replacements
3. Typography/spacing normalization
4. Component-level style updates (header, sidebar, cards, modals, agent panel)
5. Prompt template backend (API + data file + integration)
6. Prompt template frontend (tab + editor UI)
7. Run existing tests, verify no regressions

## Success Criteria

- All 28 existing tests pass
- No emoji icons remaining in the UI
- All color values reference CSS variables (no raw hex in component styles)
- Template editor: can view, edit, save, and reset templates per project
- Prompt generation uses project-specific templates when available
- Visual: light theme, consistent spacing, clear hierarchy
