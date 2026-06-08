import json
from api import vidu
from api.routes.settings import get_api_key

vidu_key = get_api_key("VIDU_API_KEY")

# 查所有submitted的任务
with open(r"C:\Users\boomer\Desktop\vidu_studio\儿子\pipeline.json", encoding="utf-8") as f:
    data = json.load(f)

# 检查所有有task_id的条目
print("=== Characters ===")
for name, info in data.get("assets", {}).get("characters", {}).items():
    tid = info.get("task_id")
    status = info.get("status")
    if tid:
        result = vidu.poll_task(vidu_key, tid)
        print(f"  {name}: pipeline_status={status}, vidu_status={result['status']}, error={result.get('error')}")

print("\n=== Scenes ===")
for name, info in data.get("assets", {}).get("scenes", {}).items():
    tid = info.get("task_id")
    status = info.get("status")
    if tid:
        result = vidu.poll_task(vidu_key, tid)
        print(f"  {name}: pipeline_status={status}, vidu_status={result['status']}, error={result.get('error')}")

print("\n=== Storyboards ===")
for key, board in data.get("storyboards", {}).items():
    tid = board.get("board_task_id")
    status = board.get("board_status")
    if tid:
        result = vidu.poll_task(vidu_key, tid)
        print(f"  {key}: pipeline_status={status}, vidu_status={result['status']}, error={result.get('error')}")
