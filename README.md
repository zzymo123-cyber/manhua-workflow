# Manhua Workflow

Manhua Workflow is a local production tool for turning a structured manhua or short-drama script folder into a trackable pipeline for characters, scenes, props, storyboards, and video parts.

It is designed for the project owner and collaborators who need a quiet, professional workflow surface: import a project, check readiness, generate prompts, submit image and video tasks, recover from failures, and download outputs.

## Current Release

v5 keeps storyboard routes in single-lane production, adds scene director analysis, route-specific storyboard planning, locked planning before final prompts, board-level asset references, backend batch submission, and synchronized migration/tests for continuing work across macOS and Windows.

## Requirements

- Python 3.10 or newer
- macOS or Windows
- API keys for the services you plan to use:
  - Vidu for image generation
  - Wetoken for video generation
  - ideaLAB-compatible Anthropic endpoint for prompt generation
  - GitHub token and repository only if Wetoken reference images must be uploaded through GitHub

## Start On macOS

```bash
chmod +x scripts/start-macos.sh
./scripts/start-macos.sh
```

The script creates `.venv`, installs `requirements.txt`, starts the app on port `8002`, and opens `http://localhost:8002`.
The browser opens only after the local health check is ready.

To use another port:

```bash
MANHUA_PORT=8010 ./scripts/start-macos.sh
```

`MANHUA_PORT` and `PORT` must be integers between `1` and `65535`.

## Start On Windows

Double-click:

```text
启动服务器.bat
```

Or run PowerShell directly:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-windows.ps1
```

The script creates `.venv`, installs `requirements.txt`, starts the app on port `8002`, and opens `http://localhost:8002`.
The browser opens only after the local health check is ready.

To use another port:

```powershell
$env:MANHUA_PORT = "8010"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-windows.ps1
```

`MANHUA_PORT` and `PORT` must be integers between `1` and `65535`.

## Configure API Keys

Open the app, click the settings icon, and save the service keys there. The LLM provider can be set to ideaLAB or DeepSeek; DeepSeek uses the OpenAI-compatible API at `https://api.deepseek.com` by default. Saved keys can be cleared from the same settings panel. For Wetoken video generation with local reference images, also fill GitHub Token, Owner, and Repo so the app can upload image references before submitting the video task. The app writes a local `settings.json`, which is intentionally ignored by git.

For a new environment, copy `settings.example.json` only as a reference. Do not commit real keys.

## Input Folder Format

Import a project folder that contains:

```text
your-project/
  character_visuals.md        optional
  scene_props_visuals.md      optional
  script/
    ep01.md
    ep02.md
```

Required files:

- `script/ep*.md`: episode scripts with scene headings

Optional files:

- `character_visuals.md`: role sections using `## 角色名`
- `scene_props_visuals.md`: scene and prop sections

If visual documents are missing, the app infers initial character, scene, and prop seeds from the scripts so the project can still be imported and then refined in the UI.

The app parses this folder and writes `pipeline.json` into the same folder.

## Production Workflow

1. Import or parse a project folder.
2. Configure API keys if the app reports missing services.
3. Generate character, scene, and prop prompts.
4. Submit image tasks and wait for completion.
5. Generate storyboard prompts after required references are ready.
6. Submit storyboard images for the selected storyboard version and page.
7. Generate video prompts from a completed storyboard output.
8. Submit video parts and download completed videos.

## Development

Install development dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

Run tests:

```bash
.venv/bin/python -m pytest -q
```

Current expected result:

```text
57 passed
```

## Local Files

Generated local files are intentionally not committed:

- `.venv/`
- `settings.json`
- `.pytest_cache/`
- `__pycache__/`
- `.impeccable/live/sessions/`
