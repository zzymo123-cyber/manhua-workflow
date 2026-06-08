# manhua-workflow 项目上下文

## 基本信息
- **位置**：`c:\Users\boomer\qcoder\manhua-workflow`
- **启动**：`启动服务器.bat` → `http://localhost:8002`
- **技术**：FastAPI + uvicorn（port 8002, reload=False），前端单页 HTML（`static/index.html`）
- **AI**：Anthropic claude-sonnet-4-6，通过 ideaLAB 内部端点（`https://idealab.alibaba-inc.com/api/anthropic`），httpx 需 `trust_env=False` 绕过 Windows 代理

## 这是什么工具
帮助制作 AI 生成漫剧（分镜图 + 视频）的工作流工具。从剧本文件出发，依次完成：
**角色图 → 场景图 → 故事板图 → 视频**

图片生成走 Vidu API，视频走 Wetoken API（Seedance 模型）。

## 核心数据结构：pipeline.json

每个项目有一个 `pipeline.json`，所有状态都存在这里。

```json
{
  "project": "项目名",
  "assets": {
    "characters": {
      "角色名": { "seed": "外貌描述文本", "draft_prompt": "生成后的提示词", "status": "needed|submitted|completed|failed" }
    },
    "scenes": {
      "场景名": { "seed": "场景描述", "draft_prompt": "", "status": "needed" }
    },
    "props": {
      "道具名": { "seed": "道具描述", "draft_prompt": "", "status": "needed" }
    }
  },
  "storyboards": {
    "s01_01": {
      "episode": 1,
      "scene_num": 1,
      "script_title": "第1集·场景1·地点名",
      "characters_in_scene": ["角色A", "角色B"],
      "scene_location": "场景名",
      "script_segment": "剧本片段文本",
      "board_status": "needed|submitted|completed|failed",
      "draft_prompt": "",
      "video_parts": [
        { "part": 1, "prompt": "", "draft_prompt": "", "video_status": "needed", "video_url": "" }
      ]
    }
  }
}
```

**storyboard key 格式**：`s{ep:02d}_{scene_num:02d}`，如 `s01_03`

## 路由结构

```
api/routes/
  project.py   — /api/project/import, /parse, /list-recent, /status
  assets.py    — /api/assets/{project_name}/{path}（旧），/api/asset-file?project_path=&file_path=（新）
  tasks.py     — /api/tasks/submit, /api/tasks/poll
  prompts.py   — /api/prompts/generate, /api/prompts/batch
  chat.py      — /api/chat（agent 对话）
  settings.py  — /api/settings（GET/PUT），存 API keys + recent_projects
```

## 关键设计决策

**项目路径**：`api/pipeline.get_project_root(project_name)` 支持绝对路径——若传入绝对路径直接使用，否则拼接 `~/Desktop/vidu_studio/{name}`。前端统一用完整路径（`state.projectPath`）传给后端，localStorage key 为 `manhua_project_path`。

**Agent 系统提示**：不把完整 pipeline.json 传给 LLM，只传摘要（名称 + 状态 + 前100字）防止 context 爆炸。Agent 需要完整内容时先发 `get_full_prompt` action，触发二次 LLM 调用。

**Agent 二步循环**（`api/routes/chat.py/_run_agent`）：
1. 第一次 LLM 调用 → 若有 `get_full_prompt` action → 读取完整内容
2. 第二次 LLM 调用（带完整内容）→ 执行修改 actions

**图片资产路径**：存在项目目录下 `{category}/{name}/{name}.png`，category 为 `characters` / `scenes_props` / `storyboards`。

**Poller**：每 10 秒轮询一次 Vidu/Wetoken 任务状态，前端每 5 秒 poll `/api/project/status`。

## 剧本标准输入目录格式

同事提供的剧本目录结构（用于自动生成 pipeline.json）：
```
{input_dir}/
  character_visuals.md    — ## 角色名 分段，内容为外貌描述
  scene_props_visuals.md  — ## 场景名 分段 + ## 关键道具 下的 ### 道具名
  characters.md           — 角色表（可选）
  overview.md             — 全剧概览（可选）
  script/
    ep01.md, ep02.md ...  — 每集剧本
```

剧本场景标题格式：`## 场景N：内/外 · 地点名 · 时间`
台词格式：`**角色名**（状态）：台词`
动作行：`△ 动作描述`

解析入口：`api/parser.py/parse_input_dir(input_dir, project_name)`，`pipeline.json` 写入输入目录本身。

## 测试
```
python -m pytest tests/ -x -q
```
28 个测试（截至 2025-06）。

## 待办 / 已知缺口

- [ ] 可编辑系统提示词模板（per-project，存 `{project_dir}/prompts/character.txt` 等）
- [ ] parser 对实际剧本文件的集成测试（`character_visuals.md` 格式需和当前文件对齐验证）
- [ ] 当前编辑器打开的剧本输入目录：`c:\Users\boomer\Desktop\剧本标准输入`
