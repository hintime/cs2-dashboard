import subprocess
import os
import json

os.environ['CSQAQ_API_TOKEN'] = 'HXGPY1R7L5W7K7F3O4K1E2N8'

# 用 --body-file 方式
body = {'page_index': 1, 'page_size': 3, 'filter': {'type': ['sticker', 'normal'], 'sort': ['price_up_1d']}, 'show_recently_price': True}
body_file = r'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard\_body.json'
with open(body_file, 'w', encoding='utf-8') as f:
    json.dump(body, f, ensure_ascii=False)

result = subprocess.run(
    ['python', r'C:\Users\Lenovo\.qclaw\workspace\skills\csqaq-market-lookup\scripts\csqaq_api.py', 'call',
     '--path', '/api/v1/info/get_rank_list', '--method', 'POST', '--body-file', body_file],
    capture_output=True, timeout=60
)

output = result.stdout.decode('utf-8', errors='replace')
lines = output.strip().split('\n')

# 找 JSON 起始
json_start = -1
for i, line in enumerate(lines):
    if line.startswith('[CALL]') or line.startswith('[STATUS]'):
        continue
    if line.startswith('{') or line.startswith('['):
        json_start = i
        break

if json_start >= 0:
    json_text = '\n'.join(lines[json_start:])
    data = json.loads(json_text)
    items = data.get('data', {}).get('data', [])
    
    # 保存到文件验证
    with open(r'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard\_skill_result.json', 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print(f"OK - {len(items)} items, first name: {items[0]['name'] if items else 'N/A'}")
else:
    print(f"No JSON found. Output: {output[:300]}")
