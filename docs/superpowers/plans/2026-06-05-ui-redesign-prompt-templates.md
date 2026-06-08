# UI Redesign + Prompt Template Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the manhua-workflow web UI from dark purple to a clean light-themed professional tool, and add per-project editable system prompt templates.

**Architecture:** In-place refactoring of `static/index.html` (single file, no splitting). CSS variables replace all hardcoded values. Lucide CDN replaces all emoji icons. New backend routes for prompt template CRUD. `prompts.py` reads project-specific templates when generating prompts.

**Tech Stack:** FastAPI, vanilla HTML/JS, Lucide (CDN), pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `static/index.html` | Modify | All CSS variables, light theme styles, Lucide integration, template editor tab |
| `api/routes/project.py` | Modify | Add GET/PUT prompt-templates routes |
| `api/routes/prompts.py` | Modify | Read project templates instead of hardcoded constants |
| `api/pipeline.py` | Modify | Add `read_prompt_templates` and `write_prompt_templates` helpers |
| `tests/test_routes.py` | Modify | Add tests for prompt-templates API |
| `tests/test_pipeline.py` | Modify | Add tests for template read/write helpers |

---

### Task 1: CSS Variables + Light Theme Foundation

**Files:**
- Modify: `static/index.html` (CSS section, lines 7-186)

This task replaces the entire `<style>` block. The new CSS variables are defined in `:root`, and all component styles reference those variables instead of raw hex values. The structure of selectors stays the same — only the values change.

- [ ] **Step 1: Replace the `<style>` block with light-theme CSS variables and token-based styles**

Replace the entire `<style>...</style>` section (lines 7-186) with the new CSS. The new block must:

1. Define `:root` with all design tokens (colors, spacing, typography, radius, shadow)
2. Replace every hardcoded color/size with the corresponding variable
3. Convert the dark theme selectors to light theme equivalents
4. Add Lucide icon sizing rules (`svg.lucide { width: 16px; height: 16px; }`)
5. Keep all existing class names and selector structure intact

New `<style>` block:

```css
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg-base: #ffffff;
  --bg-surface: #f8f9fb;
  --bg-elevated: #ffffff;
  --bg-muted: #f1f3f5;
  --text-primary: #1a1d23;
  --text-secondary: #6b7280;
  --text-muted: #9ca3af;
  --text-on-accent: #ffffff;
  --accent: #6366f1;
  --accent-hover: #4f46e5;
  --accent-light: #eef2ff;
  --accent-muted: #c7d2fe;
  --success: #22c55e;
  --success-light: #f0fdf4;
  --warning: #f59e0b;
  --warning-light: #fffbeb;
  --error: #ef4444;
  --error-light: #fef2f2;
  --border: #e5e7eb;
  --border-hover: #d1d5db;
  --text-xs: 11px;
  --text-sm: 12px;
  --text-base: 14px;
  --text-md: 16px;
  --text-lg: 18px;
  --text-xl: 20px;
  --space-1: 4px; --space-2: 8px; --space-3: 12px;
  --space-4: 16px; --space-5: 20px; --space-6: 24px;
  --space-8: 32px;
  --radius-sm: 6px; --radius-md: 8px; --radius-lg: 12px;
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
  --shadow-md: 0 2px 8px rgba(0,0,0,0.08);
  --shadow-lg: 0 4px 16px rgba(0,0,0,0.12);
  --font-mono: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
}
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: var(--bg-base); color: var(--text-primary); height: 100vh;
       display: flex; flex-direction: column; overflow: hidden;
       font-size: var(--text-base); line-height: 1.5; }
svg.lucide { width: 16px; height: 16px; stroke-width: 2; }
svg.lucide-sm { width: 14px; height: 14px; }
svg.lucide-lg { width: 20px; height: 20px; }

#header { background: var(--bg-surface); border-bottom: 1px solid var(--border);
          padding: var(--space-3) var(--space-4); display: flex; align-items: center; gap: var(--space-4);
          flex-shrink: 0; }
#header h1 { font-size: var(--text-md); font-weight: 600; color: var(--accent); }
#header .meta { font-size: var(--text-sm); color: var(--text-secondary); cursor: pointer; }
#header .meta:hover { color: var(--text-primary); }
#header .tasks-badge { background: var(--bg-muted); border-radius: 12px;
                        padding: 3px 10px; font-size: var(--text-sm); color: var(--warning); }
#header .settings-btn { margin-left: auto; background: none; border: none;
                        color: var(--text-secondary); cursor: pointer; padding: var(--space-2) var(--space-3);
                        border-radius: var(--radius-sm); display: flex; align-items: center; }
#header .settings-btn:hover { background: var(--bg-muted); color: var(--accent); }

#main { display: flex; flex: 1; overflow: hidden; }
#sidebar { width: 200px; background: var(--bg-elevated); border-right: 1px solid var(--border);
           display: flex; flex-direction: column; overflow: hidden; flex-shrink: 0; }
#phase-tabs { padding: var(--space-2); display: flex; flex-direction: column; gap: 2px;
              border-bottom: 1px solid var(--border); }
.phase-tab { padding: var(--space-2) var(--space-3); border-radius: var(--radius-sm); font-size: var(--text-sm);
             cursor: pointer; background: var(--bg-base); color: var(--text-secondary);
             border: 1px solid transparent; transition: all 0.15s;
             display: flex; align-items: center; gap: var(--space-2); }
.phase-tab.active { background: var(--accent-light); color: var(--accent); border-left: 2px solid var(--accent); }
.phase-tab:hover { color: var(--text-primary); background: var(--bg-muted); }
#sidebar-storyboard-list { flex: 1; overflow-y: auto; padding: var(--space-2); }
.episode-group { margin-bottom: var(--space-2); }
.episode-label { font-size: var(--text-xs); color: var(--text-muted); padding: var(--space-1) var(--space-2); }
.scene-card { background: var(--bg-muted); border-radius: var(--radius-sm); padding: var(--space-2); margin-bottom: 4px;
              cursor: pointer; border: 1px solid transparent; }
.scene-card:hover { background: var(--bg-surface); }
.scene-card.selected { background: var(--accent-light); border-left: 2px solid var(--accent-muted); }
.scene-card .scene-name { font-size: var(--text-sm); font-weight: 500; margin-bottom: var(--space-1); }
.scene-card .status-row { display: flex; gap: 4px; }
.status-badge { font-size: var(--text-xs); padding: 1px 5px; border-radius: 4px;
                background: var(--bg-muted); color: var(--text-muted); display: inline-flex; align-items: center; gap: 3px; }
.status-badge.done { color: var(--success); background: var(--success-light); }
.status-badge.progress { color: var(--warning); background: var(--warning-light); }
.status-badge.failed { color: var(--error); background: var(--error-light); }

#stage-progress-wrap { padding: var(--space-2); border-top: 1px solid var(--border); }
#stage-progress-wrap .stage-pipeline { display: flex; align-items: center; gap: 2px; margin-bottom: var(--space-1); flex-wrap: wrap; }
.stage-node { font-size: var(--text-xs); padding: 2px var(--space-2); border-radius: 3px; background: var(--bg-muted); color: var(--text-muted); white-space: nowrap; }
.stage-node.active { background: var(--accent-light); color: var(--accent); }
.stage-node.done { background: var(--success-light); color: var(--success); }
.stage-arrow { font-size: var(--text-xs); color: var(--text-muted); }
#progress-bar { height: 4px; background: var(--bg-muted); border-radius: 2px; margin-top: var(--space-1); }
#progress-fill { height: 100%; background: var(--accent); border-radius: 2px; transition: width 0.3s; }

#content-panel { flex: 1; overflow-y: auto; background: var(--bg-base); display: flex; flex-direction: column; }

#batch-toolbar { background: var(--bg-surface); border-bottom: 1px solid var(--border);
                 padding: var(--space-2) var(--space-4); display: none; align-items: center; gap: var(--space-2); flex-shrink: 0; }
#batch-toolbar.visible { display: flex; }
#batch-toolbar .toolbar-label { font-size: var(--text-sm); color: var(--text-secondary); margin-right: var(--space-1); }
#batch-toolbar .batch-progress { font-size: var(--text-xs); color: var(--warning); margin-left: var(--space-2); }

#grid-area { padding: var(--space-4); display: none; }
#grid-area.visible { display: block; }
.asset-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: var(--space-3); }
.asset-card { background: var(--bg-elevated); border-radius: var(--radius-md); padding: var(--space-3); cursor: pointer;
              border: 1px solid var(--border); transition: all 0.15s; position: relative;
              box-shadow: var(--shadow-sm); }
.asset-card:hover { background: var(--bg-surface); border-color: var(--border-hover); box-shadow: var(--shadow-md); }
.asset-card.selected { background: var(--accent-light); border-color: var(--accent); border-left-width: 2px; }
.asset-card.failed { border-color: var(--error); }
.asset-card .card-name { font-size: var(--text-base); font-weight: 600; margin-bottom: var(--space-2); color: var(--text-primary); }
.asset-card .card-seed { font-size: var(--text-xs); color: var(--text-muted); line-height: 1.4; max-height: 36px; overflow: hidden; }
.asset-card .card-status { margin-top: var(--space-2); }

.card-thumb { width: 100%; height: 100px; border-radius: 4px; margin-bottom: var(--space-2); background: var(--bg-muted);
              overflow: hidden; display: flex; align-items: center; justify-content: center; }
.card-thumb img { width: 100%; height: 100%; object-fit: cover; }
.card-thumb .placeholder { color: var(--text-muted); }
.card-thumb .spinner { width: 20px; height: 20px; border: 2px solid var(--border); border-top-color: var(--warning);
                       border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

#detail-panel { flex: 1; overflow-y: auto; padding: var(--space-5); display: none; }
#detail-panel.visible { display: block; }
#detail-panel h2 { font-size: var(--text-lg); font-weight: 600; margin-bottom: var(--space-3); color: var(--accent); }
.back-link { font-size: var(--text-sm); color: var(--text-secondary); cursor: pointer; margin-bottom: var(--space-3); display: inline-block; }
.back-link:hover { color: var(--accent); }
.empty-state { color: var(--text-muted); font-size: var(--text-base); text-align: center; margin-top: 60px; }
.stage-section { margin-bottom: var(--space-5); }
.stage-section h3 { font-size: var(--text-sm); color: var(--text-secondary); margin-bottom: var(--space-2); }
.prompt-editor { width: 100%; background: var(--bg-surface); border: 1px solid var(--border);
                 border-radius: var(--radius-md); padding: var(--space-3); font-size: var(--text-sm); color: var(--text-primary);
                 line-height: 1.6; resize: vertical; min-height: 120px; }
.prompt-editor:focus { outline: none; border-color: var(--accent-muted); }
.img-preview { width: 100%; max-height: 300px; object-fit: contain; border-radius: var(--radius-md);
               background: var(--bg-surface); margin-bottom: var(--space-3); }
.btn { padding: var(--space-2) var(--space-4); border-radius: var(--radius-sm); font-size: var(--text-sm); cursor: pointer;
       border: none; font-weight: 500; text-decoration: none; display: inline-flex; align-items: center; gap: var(--space-1); }
.btn-primary { background: var(--accent); color: var(--text-on-accent); }
.btn-primary:hover { background: var(--accent-hover); }
.btn-primary:disabled { background: var(--bg-muted); color: var(--text-muted); cursor: not-allowed; }
.btn-secondary { background: var(--bg-muted); color: var(--text-secondary); }
.btn-secondary:hover { background: var(--bg-surface); color: var(--text-primary); }
.btn-secondary:disabled { background: var(--bg-muted); color: var(--text-muted); cursor: not-allowed; }
.btn-danger { background: var(--error); color: var(--text-on-accent); }
.btn-row { display: flex; gap: var(--space-2); margin-top: var(--space-3); flex-wrap: wrap; }
.video-part-card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md);
                   padding: var(--space-3); margin-bottom: var(--space-2); }
.video-part-card .part-header { font-size: var(--text-sm); font-weight: 600; color: var(--accent); margin-bottom: var(--space-2); }

.modal-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.3);
                  z-index: 100; justify-content: center; align-items: center; }
.modal-overlay.visible { display: flex; }
.modal { background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-lg);
         padding: var(--space-6); width: 440px; max-width: 90vw; box-shadow: var(--shadow-lg); }
.modal h2 { font-size: var(--text-lg); color: var(--accent); margin-bottom: var(--space-4); }
.modal label { display: block; font-size: var(--text-sm); color: var(--text-secondary); margin-bottom: var(--space-1); margin-top: var(--space-3); }
.modal input { width: 100%; background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-sm);
              padding: var(--space-2) var(--space-3); font-size: var(--text-sm); color: var(--text-primary); }
.modal input:focus { outline: none; border-color: var(--accent-muted); }
.modal .btn-row { margin-top: var(--space-5); justify-content: flex-end; }

#agent-panel { position: fixed; right: 0; top: 0; bottom: 0; width: 320px;
               background: var(--bg-elevated); border-left: 1px solid var(--border);
               display: flex; flex-direction: column; z-index: 50;
               transform: translateX(100%); transition: transform 0.2s ease;
               box-shadow: var(--shadow-lg); }
#agent-panel.open { transform: translateX(0); }
#agent-panel-header { padding: var(--space-3) var(--space-4); border-bottom: 1px solid var(--border);
                       display: flex; align-items: center; gap: var(--space-2); flex-shrink: 0; }
#agent-panel-header span { font-size: var(--text-sm); font-weight: 600; color: var(--accent); flex: 1; }
#agent-clear { background: none; border: 1px solid var(--border); border-radius: 5px;
               color: var(--text-muted); font-size: var(--text-xs); padding: 3px var(--space-2); cursor: pointer; }
#agent-clear:hover { color: var(--text-secondary); border-color: var(--border-hover); }
#agent-close { background: none; border: none; color: var(--text-muted); cursor: pointer; padding: var(--space-1) var(--space-2); line-height: 1;
               display: flex; align-items: center; }
#agent-close:hover { color: var(--text-secondary); }
#agent-messages { flex: 1; overflow-y: auto; padding: var(--space-3); display: flex; flex-direction: column; gap: var(--space-2); }
.amsg-user { align-self: flex-end; background: var(--accent-light); border-radius: 10px 10px 2px 10px;
             padding: var(--space-2) var(--space-3); font-size: var(--text-sm); color: var(--text-primary); max-width: 85%; }
.amsg-assistant { align-self: flex-start; background: var(--bg-muted); border-radius: 10px 10px 10px 2px;
                  padding: var(--space-2) var(--space-3); font-size: var(--text-sm); color: var(--text-primary); max-width: 85%; line-height: 1.5; }
.amsg-tool { align-self: flex-start; display: flex; align-items: center; gap: var(--space-2);
             font-size: var(--text-xs); color: var(--text-muted); padding: var(--space-1) 0; }
.amsg-tool .tool-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--border); flex-shrink: 0; }
.amsg-tool.ok .tool-dot { background: var(--success); }
.amsg-tool.fail .tool-dot { background: var(--error); }
.amsg-thinking { align-self: flex-start; font-size: var(--text-xs); color: var(--text-muted); padding: var(--space-1) 0;
                  display: flex; align-items: center; gap: var(--space-2); }
.amsg-thinking .dots span { animation: blink 1.2s infinite; display: inline-block; }
.amsg-thinking .dots span:nth-child(2) { animation-delay: 0.2s; }
.amsg-thinking .dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes blink { 0%,80%,100%{opacity:0.2} 40%{opacity:1} }
#agent-input-row { padding: var(--space-3) var(--space-3); border-top: 1px solid var(--border); display: flex; gap: var(--space-2); flex-shrink: 0; }
#agent-input { flex: 1; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-sm);
               padding: var(--space-2) var(--space-3); font-size: var(--text-sm); color: var(--text-primary); resize: none; height: 36px;
               line-height: 1.4; }
#agent-input:focus { outline: none; border-color: var(--accent-muted); }
#agent-input:disabled { opacity: 0.5; }
#agent-send { background: var(--accent); color: var(--text-on-accent); border: none; border-radius: var(--radius-sm);
              padding: var(--space-2) var(--space-4); font-size: var(--text-sm); cursor: pointer; white-space: nowrap; }
#agent-send:hover { background: var(--accent-hover); }
#agent-send:disabled { background: var(--bg-muted); cursor: not-allowed; }
#agent-fab { position: fixed; right: var(--space-4); bottom: 20px; background: var(--accent); color: var(--text-on-accent);
             border: none; border-radius: 50%; width: 44px; height: 44px;
             cursor: pointer; box-shadow: 0 2px 12px rgba(99,102,241,0.4); z-index: 49;
             display: flex; align-items: center; justify-content: center; }
#agent-fab:hover { background: var(--accent-hover); }
#agent-fab.hidden { display: none; }
.warn-banner { background: var(--warning-light); border: 1px solid var(--warning); border-radius: var(--radius-sm);
               padding: var(--space-2) var(--space-3); font-size: var(--text-sm); color: var(--warning); margin-bottom: var(--space-3); }
.block-banner { background: var(--warning-light); border: 1px solid var(--warning); border-radius: var(--radius-sm);
               padding: var(--space-2) var(--space-3); font-size: var(--text-sm); color: #e65100; margin-bottom: var(--space-3); }
.error-banner { background: var(--error-light); border: 1px solid var(--error); border-radius: var(--radius-sm);
                padding: var(--space-2) var(--space-3); font-size: var(--text-sm); color: var(--error); margin-bottom: var(--space-3); }
.recent-project-item { background: var(--bg-elevated); border: 1px solid var(--border); border-radius: var(--radius-sm);
                        padding: var(--space-2) var(--space-3); cursor: pointer; display: flex; align-items: center; gap: var(--space-3); }
.recent-project-item:hover { background: var(--bg-surface); border-color: var(--accent-muted); }
.recent-project-item .rp-name { font-size: var(--text-base); font-weight: 600; color: var(--text-primary); flex-shrink: 0; }
.recent-project-item .rp-path { font-size: var(--text-xs); color: var(--text-muted); flex: 1; overflow: hidden;
                                  text-overflow: ellipsis; white-space: nowrap; }

/* Template editor */
.template-editor-wrap { padding: var(--space-5); display: flex; flex-direction: column; height: 100%; }
.template-editor-wrap h2 { font-size: var(--text-lg); color: var(--accent); margin-bottom: var(--space-4); }
.template-type-select { width: 100%; background: var(--bg-base); border: 1px solid var(--border);
                        border-radius: var(--radius-sm); padding: var(--space-2) var(--space-3);
                        font-size: var(--text-sm); color: var(--text-primary); margin-bottom: var(--space-3); }
.template-type-select:focus { outline: none; border-color: var(--accent-muted); }
.template-textarea { flex: 1; width: 100%; background: var(--bg-surface); border: 1px solid var(--border);
                     border-radius: var(--radius-md); padding: var(--space-3); font-size: var(--text-sm);
                     color: var(--text-primary); line-height: 1.6; resize: none; font-family: var(--font-mono); }
.template-textarea:focus { outline: none; border-color: var(--accent-muted); }
```

- [ ] **Step 2: Verify page still loads**

Start server: `cd c:\Users\boomer\qcoder\manhua-workflow && python main.py`
Open browser `http://localhost:8002` — page should render in light theme, all elements visible, no broken styles.

- [ ] **Step 3: Run existing tests**

Run: `cd c:\Users\boomer\qcoder\manhua-workflow && python -m pytest tests/ -v`
Expected: All 28 tests pass (UI changes don't affect backend tests)

- [ ] **Step 4: Commit**

```bash
cd c:\Users\boomer\qcoder\manhua-workflow && git add static/index.html && git commit -m "feat: replace dark theme with light-themed CSS variable system"
```

---

### Task 2: Lucide CDN + Icon Replacements (HTML)

**Files:**
- Modify: `static/index.html` (HTML body + JS)

This task adds Lucide CDN script, replaces all emoji icons with `<i data-lucide="...">` elements, and updates JS functions to call `lucide.createIcons()` after DOM updates.

- [ ] **Step 1: Add Lucide CDN script tag**

In the `<head>` section, add before closing `</head>`:

```html
<script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
```

- [ ] **Step 2: Replace emoji icons in HTML body**

Replace these elements in the HTML:

1. Settings button: `&#9881;` → `<i data-lucide="settings"></i>`
2. Agent FAB: `&#10024;` → `<i data-lucide="sparkles"></i>`
3. Agent close: `&#10005;` → `<i data-lucide="x"></i>`
4. Phase tabs: change each `<div class="phase-tab" data-phase="...">角色</div>` to include Lucide icon:
   - Characters: `<div class="phase-tab" data-phase="characters"><i data-lucide="users"></i> 角色</div>`
   - Scenes: `<div class="phase-tab" data-phase="scenes_props"><i data-lucide="image"></i> 场景</div>`
   - Storyboards: `<div class="phase-tab" data-phase="storyboards"><i data-lucide="layout-grid"></i> 故事板</div>`
   - Video: `<div class="phase-tab" data-phase="video_prompts"><i data-lucide="video"></i> 视频</div>`
   - Templates: `<div class="phase-tab" data-phase="templates"><i data-lucide="file-text"></i> 模板</div>`

5. Empty hint default text stays text-only (no icon needed).

- [ ] **Step 3: Update JS `statusIcon()` function to return Lucide HTML**

Replace the `statusIcon` function:

```javascript
function statusIcon(s) {
  const icons = {
    completed: '<i data-lucide="check" class="lucide-sm"></i>',
    submitted: '<i data-lucide="loader" class="lucide-sm" style="animation:spin 0.8s linear infinite"></i>',
    failed: '<i data-lucide="x" class="lucide-sm"></i>',
    needed: '<i data-lucide="circle" class="lucide-sm"></i>',
    pending: '<i data-lucide="circle" class="lucide-sm"></i>',
  };
  return icons[s] || '<i data-lucide="minus" class="lucide-sm"></i>';
}
```

- [ ] **Step 4: Add `lucide.createIcons()` calls after every DOM update**

After every function that sets `innerHTML` on the page, add `lucide.createIcons()`:

1. At end of `renderAll()`: `lucide.createIcons();`
2. At end of `renderAssetGrid()`: (already covered by renderAll)
3. At end of `renderDetail()` sub-functions: covered by renderAll
4. At end of `renderSidebarList()`: covered by renderAll
5. At end of `_loadRecentProjects()`: `lucide.createIcons();`
6. At end of `doParsePreview()` innerHTML update: `lucide.createIcons();`
7. After `appendAgentMsg()` / `appendAgentTool()`: `lucide.createIcons();`

The simplest approach: add `lucide.createIcons()` at the end of `renderAll()`, and also at the end of any function that updates DOM outside of `renderAll` (like `_loadRecentProjects`, `doParsePreview`, and the agent message functions).

- [ ] **Step 5: Update JS to handle the new "templates" phase**

In the phase tab click handler (currently near bottom of `<script>`), the existing code is:

```javascript
document.querySelectorAll('.phase-tab').forEach(tab => {
  tab.onclick = () => {
    state.currentPhase = tab.dataset.phase;
    state.selectedScene = null;
    renderAll();
  };
});
```

This already works generically — it sets `state.currentPhase` from `tab.dataset.phase`. No change needed. But `renderMainArea()` needs a new branch for the templates phase. Add after the `video_prompts` branch:

```javascript
} else if (state.currentPhase === 'templates') {
  toolbar.classList.remove('visible');
  gridArea.classList.remove('visible');
  emptyHint.style.display = 'none';
  detailPanel.classList.add('visible');
  renderTemplateEditor(detailPanel);
}
```

- [ ] **Step 6: Verify page renders with Lucide icons**

Start server, open browser. All icons should show as Lucide SVGs instead of emoji. Phase tabs should have icons + text. Status badges should use Lucide icons.

- [ ] **Step 7: Run existing tests**

Run: `cd c:\Users\boomer\qcoder\manhua-workflow && python -m pytest tests/ -v`
Expected: All 28 tests pass

- [ ] **Step 8: Commit**

```bash
cd c:\Users\boomer\qcoder\manhua-workflow && git add static/index.html && git commit -m "feat: replace all emoji icons with Lucide, add templates phase tab"
```

---

### Task 3: Prompt Template Backend — Pipeline Helpers

**Files:**
- Modify: `api/pipeline.py` (add template read/write helpers)
- Modify: `tests/test_pipeline.py` (add template helper tests)

- [ ] **Step 1: Write failing test for `read_prompt_templates`**

In `tests/test_pipeline.py`, add:

```python
def test_read_prompt_templates_not_exist_returns_defaults(tmp_project):
    """When prompt_templates.json doesn't exist, return built-in defaults"""
    from api.pipeline import read_prompt_templates
    result = read_prompt_templates(tmp_project)
    assert "character" in result
    assert "scene" in result
    assert result["character"]  # non-empty string

def test_write_and_read_prompt_templates(tmp_project):
    from api.pipeline import write_prompt_templates, read_prompt_templates
    data = {"character": "custom char prompt", "scene": "custom scene prompt"}
    write_prompt_templates(tmp_project, data)
    result = read_prompt_templates(tmp_project)
    assert result["character"] == "custom char prompt"
    assert result["scene"] == "custom scene prompt"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd c:\Users\boomer\qcoder\manhua-workflow && python -m pytest tests/test_pipeline.py::test_read_prompt_templates_not_exist_returns_defaults tests/test_pipeline.py::test_write_and_read_prompt_templates -v`
Expected: FAIL (ImportError or AttributeError — functions don't exist yet)

- [ ] **Step 3: Implement `read_prompt_templates` and `write_prompt_templates` in `api/pipeline.py`**

Add at the end of `api/pipeline.py`:

```python
# ── 提示词模板默认值（与 prompts.py 常量同步）──
_PROMPT_TEMPLATE_DEFAULTS = None  # lazy-loaded

def _get_prompt_template_defaults() -> dict:
    """延迟加载默认值（避免循环 import）"""
    global _PROMPT_TEMPLATE_DEFAULTS
    if _PROMPT_TEMPLATE_DEFAULTS is None:
        from api.routes.prompts import CHARACTER_SYSTEM, SCENE_SYSTEM, PROP_SYSTEM, STORYBOARD_SYSTEM, VIDEO_SYSTEM
        _PROMPT_TEMPLATE_DEFAULTS = {
            "character": CHARACTER_SYSTEM,
            "scene": SCENE_SYSTEM,
            "prop": PROP_SYSTEM,
            "storyboard": STORYBOARD_SYSTEM,
            "video": VIDEO_SYSTEM,
        }
    return _PROMPT_TEMPLATE_DEFAULTS


def read_prompt_templates(project_dir: Path) -> dict:
    """读取 prompt_templates.json，不存在则返回默认值"""
    path = project_dir / "prompt_templates.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return _get_prompt_template_defaults()


def write_prompt_templates(project_dir: Path, data: dict) -> None:
    """原子写入 prompt_templates.json"""
    path = project_dir / "prompt_templates.json"
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get_prompt_template_defaults() -> dict:
    """返回内置默认模板（不读文件），供 Reset to Default 使用"""
    return _get_prompt_template_defaults()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd c:\Users\boomer\qcoder\manhua-workflow && python -m pytest tests/test_pipeline.py -v`
Expected: All tests pass (including the 2 new ones)

- [ ] **Step 5: Commit**

```bash
cd c:\Users\boomer\qcoder\manhua-workflow && git add api/pipeline.py tests/test_pipeline.py && git commit -m "feat: add prompt template read/write helpers in pipeline.py"
```

---

### Task 4: Prompt Template Backend — API Routes

**Files:**
- Modify: `api/routes/project.py` (add GET/PUT prompt-templates routes)
- Modify: `tests/test_routes.py` (add route tests)

- [ ] **Step 1: Write failing tests for prompt-templates API**

In `tests/test_routes.py`, add:

```python
def test_get_prompt_templates_defaults(tmp_path):
    """GET prompt-templates returns defaults when file doesn't exist"""
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {"project": "测试项目", "assets": {}, "storyboards": {}}
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.project.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.get("/api/project/prompt-templates", params={"project_name": "测试项目"})
    assert resp.status_code == 200
    data = resp.json()
    assert "character" in data
    assert len(data["character"]) > 0

def test_get_prompt_templates_with_defaults_flag(tmp_path):
    """GET prompt-templates?defaults=true returns built-in defaults without reading file"""
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()

    with patch("api.routes.project.pl.VIDU_STUDIO_ROOT", tmp_path):
        resp = client.get("/api/project/prompt-templates", params={"project_name": "测试项目", "defaults": "true"})
    assert resp.status_code == 200
    assert "character" in resp.json()

def test_put_prompt_templates(tmp_path):
    """PUT prompt-templates saves and can be read back"""
    project_dir = tmp_path / "测试项目"
    project_dir.mkdir()
    pipeline_data = {"project": "测试项目", "assets": {}, "storyboards": {}}
    (project_dir / "pipeline.json").write_text(json.dumps(pipeline_data, ensure_ascii=False), encoding="utf-8")

    with patch("api.routes.project.pl.VIDU_STUDIO_ROOT", tmp_path):
        # Save custom template
        resp = client.put("/api/project/prompt-templates",
                          params={"project_name": "测试项目"},
                          json={"character": "自定义角色模板"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Read back
        resp = client.get("/api/project/prompt-templates", params={"project_name": "测试项目"})
        assert resp.status_code == 200
        assert resp.json()["character"] == "自定义角色模板"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd c:\Users\boomer\qcoder\manhua-workflow && python -m pytest tests/test_routes.py::test_get_prompt_templates_defaults tests/test_routes.py::test_get_prompt_templates_with_defaults_flag tests/test_routes.py::test_put_prompt_templates -v`
Expected: FAIL (404 — routes don't exist yet)

- [ ] **Step 3: Add GET/PUT prompt-templates routes to `api/routes/project.py`**

Add at the end of `api/routes/project.py`:

```python


@router.get("/prompt-templates")
async def get_prompt_templates(project_name: str, defaults: bool = False):
    """读取项目提示词模板。defaults=true 时返回内置默认值"""
    project_dir = pl.get_project_root(project_name)
    if defaults:
        return pl.get_prompt_template_defaults()
    return pl.read_prompt_templates(project_dir)


class UpdateTemplatesRequest(BaseModel):
    character: str | None = None
    scene: str | None = None
    prop: str | None = None
    storyboard: str | None = None
    video: str | None = None


@router.put("/prompt-templates")
async def update_prompt_templates(project_name: str, req: UpdateTemplatesRequest):
    """更新项目提示词模板（部分更新）"""
    project_dir = pl.get_project_root(project_name)
    current = pl.read_prompt_templates(project_dir)
    for key, value in req.model_dump().items():
        if value is not None:
            current[key] = value
    pl.write_prompt_templates(project_dir, current)
    return {"ok": True}
```

Note: `project.py` already has `from fastapi import APIRouter, HTTPException` and `from pydantic import BaseModel`. We just need to add the two new routes and the `UpdateTemplatesRequest` model. FastAPI auto-recognizes simple string query params like `project_name` and `defaults`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd c:\Users\boomer\qcoder\manhua-workflow && python -m pytest tests/test_routes.py -v`
Expected: All route tests pass (including the 3 new ones)

- [ ] **Step 5: Commit**

```bash
cd c:\Users\boomer\qcoder\manhua-workflow && git add api/routes/project.py tests/test_routes.py && git commit -m "feat: add GET/PUT prompt-templates API routes"
```

---

### Task 5: Prompt Generation Integration — Use Project Templates

**Files:**
- Modify: `api/routes/prompts.py` (read project templates instead of hardcoded constants)

- [ ] **Step 1: Modify `generate_prompt_endpoint` to read project templates**

In `api/routes/prompts.py`, the function `generate_prompt_endpoint` currently uses hardcoded constants (CHARACTER_SYSTEM, SCENE_SYSTEM, etc.). Change it to read from project templates first.

Replace the system prompt selection logic. Currently each branch does `system = CHARACTER_SYSTEM` etc. Change to:

```python
@router.post("/generate")
async def generate_prompt_endpoint(req: GenerateRequest):
    api_key = get_api_key("IDEALAB_API_KEY")
    project_dir = pl.get_project_root(req.project_name)

    # Read project-specific templates, fall back to code defaults
    templates = pl.read_prompt_templates(project_dir)

    if req.type == "character":
        system = templates.get("character", CHARACTER_SYSTEM)
        user_msg = f"角色名：{req.name}\n描述：{req.appearance_seed}"
        prompt = llm.generate_prompt(api_key, system, user_msg)
        _save_draft_prompt(project_dir, "characters", req.name, prompt)
        return {"prompt": prompt}

    elif req.type == "scene":
        system = templates.get("scene", SCENE_SYSTEM)
        user_msg = f"场景名：{req.name}\n描述：{req.appearance_seed}"
        prompt = llm.generate_prompt(api_key, system, user_msg)
        _save_draft_prompt(project_dir, "scenes", req.name, prompt)
        return {"prompt": prompt}

    elif req.type == "prop":
        system = templates.get("prop", PROP_SYSTEM)
        user_msg = f"道具名：{req.name}\n描述：{req.appearance_seed}"
        prompt = llm.generate_prompt(api_key, system, user_msg)
        _save_draft_prompt(project_dir, "props", req.name, prompt)
        return {"prompt": prompt}

    elif req.type == "storyboard":
        system = templates.get("storyboard", STORYBOARD_SYSTEM)
        # rest unchanged
        char_info = []
        for char_name in (req.characters or []):
            optimized = pl.get_prompt_optimized(project_dir, "characters", char_name)
            char_info.append({"name": char_name, "appearance": optimized or char_name})
        scene_optimized = pl.get_prompt_optimized(project_dir, "scenes_props", req.scene_location or "")
        user_msg = (
            f"场景：{req.scene_key}\n"
            f"角色信息：{char_info}\n"
            f"场景色调：{scene_optimized or ''}\n"
            f"剧本段落：{req.script_segment or ''}"
        )
        prompt = llm.generate_prompt(api_key, system, user_msg)
        return {"prompt": prompt}

    elif req.type == "video":
        system = templates.get("video", VIDEO_SYSTEM)
        # rest unchanged
        board_meta_dir = project_dir / "storyboards" / (req.scene_key or "")
        panels = req.panels or []
        board_optimized = ""
        if board_meta_dir.exists():
            import json
            meta_path = board_meta_dir / "meta.json"
            if meta_path.exists():
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                primary = meta.get("primary_image")
                for v in meta.get("versions", []):
                    if v.get("filename") == primary:
                        board_optimized = v.get("prompt", {}).get("optimized", "")
                        if not panels:
                            panels = v.get("panels", [])
        user_msg = (
            f"故事板名：{req.scene_key}\n"
            f"色调风格段：{board_optimized}\n"
            f"panels（9格）：{panels}\n"
            f"剧本台词/动作行：{req.script_segment or ''}"
        )
        prompt = llm.generate_prompt(api_key, system, user_msg)
        return {"prompt": prompt, "raw": prompt}

    else:
        raise HTTPException(status_code=400, detail=f"未知类型: {req.type}")
```

The key change: each `system = CONSTANT` line becomes `system = templates.get("type", CONSTANT)`.

- [ ] **Step 2: Run all tests**

Run: `cd c:\Users\boomer\qcoder\manhua-workflow && python -m pytest tests/ -v`
Expected: All 31 tests pass (28 original + 3 new template tests). The existing prompt tests still pass because `templates.get("character", CHARACTER_SYSTEM)` falls back to the constant when no project template file exists.

- [ ] **Step 3: Commit**

```bash
cd c:\Users\boomer\qcoder\manhua-workflow && git add api/routes/prompts.py && git commit -m "feat: prompt generation reads project-specific templates with fallback to defaults"
```

---

### Task 6: Template Editor Frontend

**Files:**
- Modify: `static/index.html` (JS section — add template editor render function + API calls)

- [ ] **Step 1: Add template state variable and render function**

In the JS `state` object, add:

```javascript
templateCache: null,  // { character: "...", scene: "...", ... }
templateType: 'character',  // currently selected type
```

Add `renderTemplateEditor` function:

```javascript
function renderTemplateEditor(container) {
  if (!state.templateCache) {
    loadTemplates();
    container.innerHTML = '<div class="empty-state"><i data-lucide="loader"></i> 加载模板...</div>';
    lucide.createIcons();
    return;
  }
  const types = ['character', 'scene', 'prop', 'storyboard', 'video'];
  const labels = { character: '角色', scene: '场景', prop: '道具', storyboard: '故事板', video: '视频' };
  const currentText = state.templateCache[state.templateType] || '';

  container.innerHTML = `
    <div class="template-editor-wrap">
      <h2>提示词模板</h2>
      <select class="template-type-select" id="template-type-select">
        ${types.map(t => `<option value="${t}" ${t === state.templateType ? 'selected' : ''}>${labels[t]}</option>`).join('')}
      </select>
      <textarea class="template-textarea" id="template-textarea">${currentText}</textarea>
      <div class="btn-row">
        <button class="btn btn-secondary" onclick="resetTemplate()">重置为默认</button>
        <button class="btn btn-primary" onclick="saveTemplate()">保存</button>
      </div>
    </div>`;

  document.getElementById('template-type-select').onchange = function() {
    state.templateType = this.value;
    document.getElementById('template-textarea').value = state.templateCache[state.templateType] || '';
  };
  lucide.createIcons();
}
```

- [ ] **Step 2: Add `loadTemplates`, `resetTemplate`, `saveTemplate` functions**

```javascript
async function loadTemplates() {
  if (!state.projectPath) return;
  try {
    const resp = await fetch(`/api/project/prompt-templates?project_name=${encodeURIComponent(state.projectPath)}`);
    if (resp.ok) {
      state.templateCache = await resp.json();
      renderAll();
    }
  } catch(e) {}
}

async function resetTemplate() {
  if (!confirm('确认重置为默认模板？当前选中类型的模板将被覆盖。')) return;
  if (!state.projectPath) return;
  try {
    const resp = await fetch(`/api/project/prompt-templates?project_name=${encodeURIComponent(state.projectPath)}&defaults=true`);
    if (resp.ok) {
      const defaults = await resp.json();
      state.templateCache[state.templateType] = defaults[state.templateType];
      document.getElementById('template-textarea').value = defaults[state.templateType];
    }
  } catch(e) { alert('重置失败：' + e.message); }
}

async function saveTemplate() {
  if (!state.projectPath) return;
  const text = document.getElementById('template-textarea').value;
  const body = {};
  body[state.templateType] = text;
  try {
    const resp = await fetch(`/api/project/prompt-templates?project_name=${encodeURIComponent(state.projectPath)}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    if (resp.ok) {
      state.templateCache[state.templateType] = text;
      alert('模板已保存');
    } else {
      const e = await resp.json().catch(()=>({}));
      alert('保存失败：' + (e.detail || resp.status));
    }
  } catch(e) { alert('保存失败：' + e.message); }
}
```

- [ ] **Step 3: Clear templateCache when switching projects**

In `loadProject()`, after `state.projectPath = projectPath;`, add:

```javascript
state.templateCache = null;
```

- [ ] **Step 4: Verify template editor works in browser**

Start server, open browser, click "模板" tab. Dropdown should show 5 types. Textarea should show the default template text. "重置为默认" should reset. "保存" should persist.

- [ ] **Step 5: Run all tests**

Run: `cd c:\Users\boomer\qcoder\manhua-workflow && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
cd c:\Users\boomer\qcoder\manhua-workflow && git add static/index.html && git commit -m "feat: add prompt template editor UI with load/save/reset"
```

---

### Task 7: Also Update Chat Route to Use Project Templates

The `api/routes/chat.py` `_build_system_prompt` function currently doesn't use project templates for the agent's system prompt. The agent itself doesn't need templates (it's a conversational assistant), so no change needed here. But the `_do_generate_prompt` function in chat.py does call prompt generation — which already reads project templates via Task 5's change. No additional change needed.

This task is **skipped** — already covered by Task 5's integration.

---

### Task 8: Also Update Poller to Support Arbitrary Project Paths

The poller currently only scans `~/Desktop/vidu_studio/`. With the new `project_path` (absolute path) feature, the poller should also scan recent projects from settings.json. However, the spec explicitly states this is out of scope for this redesign. The poller issue is pre-existing and was not requested. **Skip.**

---

### Task 9: Final Verification

- [ ] **Step 1: Run all tests**

Run: `cd c:\Users\boomer\qcoder\manhua-workflow && python -m pytest tests/ -v`
Expected: All tests pass (28 original + 3 template API tests + 2 template helper tests = 33 total)

- [ ] **Step 2: Visual check — no emoji icons remaining**

Open browser `http://localhost:8002`. Verify:
- No emoji (✓ ✗ ○ ✨ ⚙ □) anywhere in the UI
- All status badges use Lucide icons
- Phase tabs show Lucide icons + text labels
- Settings button shows Lucide `settings` icon
- Assistant FAB shows Lucide `sparkles` icon

- [ ] **Step 3: Functional check — template editor**

1. Open a project via import dialog
2. Click "模板" tab
3. Select different template types in dropdown — textarea content should switch
4. Edit text, click "保存" — should persist
5. Click "重置为默认" — should confirm and reset
6. Go to "角色" tab, click "生成提示词" — should use the project template (if saved custom one, verify it's different from default)