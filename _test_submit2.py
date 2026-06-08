import requests
import json

project_path = r"C:\Users\boomer\Desktop\vidu_studio\儿子"

# 1. 先读当前pipeline看哪些storyboard有draft_prompt
with open(project_path + "/pipeline.json", encoding="utf-8") as f:
    data = json.load(f)

for key, board in data.get("storyboards", {}).items():
    status = board.get("board_status", "needed")
    has_draft = bool(board.get("draft_prompt"))
    has_parts = len(board.get("video_parts", []))
    print(f"{key}: board_status={status}, has_draft={has_draft}, video_parts={has_parts}")

# 2. 模拟前端提交（带image_paths）
print("\n--- Testing storyboard submit with images ---")
board = data["storyboards"]["E01-S1"]
image_paths = []
for char in (board.get("characters_in_scene") or []):
    image_paths.append(f"characters/{char}/{char}.png")
if board.get("scene_location"):
    image_paths.append(f"scenes_props/{board['scene_location']}/{board['scene_location']}.png")
print(f"Image paths: {image_paths}")

payload = {
    "type": "storyboard",
    "project_name": project_path,
    "scene_key": "E01-S1",
    "prompt": board.get("draft_prompt", "test prompt"),
    "image_paths": image_paths
}
resp = requests.post("http://localhost:8000/api/tasks/submit", json=payload)
print(f"Status: {resp.status_code}")
print(f"Body: {resp.text[:500]}")
