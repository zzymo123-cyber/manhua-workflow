import json

with open(r'C:\Users\boomer\Desktop\vidu_studio\儿子\pipeline.json', encoding='utf-8') as f:
    data = json.load(f)

# find failed/submitted storyboards
for key, board in data.get('storyboards', {}).items():
    status = board.get('board_status', '')
    if status in ('failed', 'submitted'):
        task_id = board.get('board_task_id', 'N/A')
        print(f'Storyboard {key}: status={status}, task_id={task_id}')

# find failed/submitted assets
for cat in ['characters', 'scenes', 'props']:
    for name, info in data.get('assets', {}).get(cat, {}).items():
        status = info.get('status', '')
        if status in ('failed', 'submitted'):
            task_id = info.get('task_id', 'N/A')
            print(f'Asset {cat}/{name}: status={status}, task_id={task_id}')

print('--- Done ---')
