import subprocess
import os
import sys

# 设置环境
os.environ['CSQAQ_API_TOKEN'] = 'csqaqapi_HXGPY1R7L5W7K7F3O4K1E2N8'

# 调用 skill CLI
result = subprocess.run(
    ['python', r'C:\Users\Lenovo\.qclaw\workspace\skills\csqaq-market-lookup\scripts\csqaq_api.py', 'call',
     '--path', '/api/v1/info/get_rank_list',
     '--method', 'POST',
     '--body', '{"page_index": 1, "page_size": 5, "filter": {"type": ["sticker", "normal"], "sort": ["price_up_1d"]}, "show_recently_price": true}'],
    capture_output=True,
    timeout=30
)

print(f"Return code: {result.returncode}")
print(f"stdout length: {len(result.stdout)}")
print(f"stderr: {result.stderr.decode('gbk', errors='replace')[:500] if result.stderr else 'None'}")
print()

# 尝试不同编码解码 stdout
for enc in ['gbk', 'utf-8', 'cp936']:
    try:
        decoded = result.stdout.decode(enc, errors='replace')
        print(f"=== {enc} decoded (first 800 chars) ===")
        print(decoded[:800])
        print()
    except Exception as e:
        print(f"{enc} decode error: {e}")
