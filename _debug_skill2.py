import subprocess
import os
import json
import sys

# 设置环境
os.environ['CSQAQ_API_TOKEN'] = 'csqaqapi_HXGPY1R7L5W7K7F3O4K1E2N8'

# 写入 body 文件
body = {
    'page_index': 1,
    'page_size': 5,
    'filter': {'type': ['sticker', 'normal'], 'sort': ['price_up_1d']},
    'show_recently_price': True
}
body_file = r'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard\_body.json'
with open(body_file, 'w', encoding='utf-8') as f:
    json.dump(body, f, ensure_ascii=False)

# 调用 skill CLI
result = subprocess.run(
    ['python', r'C:\Users\Lenovo\.qclaw\workspace\skills\csqaq-market-lookup\scripts\csqaq_api.py', 'call',
     '--path', '/api/v1/info/get_rank_list',
     '--method', 'POST',
     '--body-file', body_file],
    capture_output=True,
    timeout=60
)

print(f"Return code: {result.returncode}")
print(f"stdout bytes length: {len(result.stdout)}")
print()

# 尝试不同编码解码 stdout
for enc in ['gbk', 'utf-8']:
    try:
        decoded = result.stdout.decode(enc, errors='replace')
        print(f"=== {enc} decoded ===")
        print(decoded[:1500])
        print()
    except Exception as e:
        print(f"{enc} decode error: {e}")

if result.stderr:
    print("=== stderr (gbk) ===")
    print(result.stderr.decode('gbk', errors='replace')[:500])
