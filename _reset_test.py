import json

path = r"C:\Users\boomer\Desktop\vidu_studio\儿子\pipeline.json"
with open(path, encoding="utf-8") as f:
    data = json.load(f)

# Reset E01-S1 from my test submission
board = data["storyboards"]["E01-S1"]
if board.get("board_status") == "submitted":
    board["board_status"] = "needed"
    if "board_task_id" in board:
        del board["board_task_id"]
    print("Reset E01-S1 to needed")

with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("Done")
