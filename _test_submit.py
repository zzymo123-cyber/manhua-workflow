import requests
import json

# 模拟提交 storyboard
payload = {
    "type": "storyboard",
    "project_name": r"C:\Users\boomer\Desktop\vidu_studio\儿子",
    "scene_key": "E01-S1",
    "prompt": "test storyboard prompt",
    "image_paths": []
}

resp = requests.post("http://localhost:8000/api/tasks/submit", json=payload)
print(f"Status: {resp.status_code}")
print(f"Body: {resp.text}")
