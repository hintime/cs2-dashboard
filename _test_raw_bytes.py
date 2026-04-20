import subprocess
import os

os.environ['CSQAQ_API_TOKEN'] = 'HXGPY1R7L5W7K7F3O4K1E2N8'

body = {'page_index': 1, 'page_size': 2, 'filter': {'type': ['sticker', 'normal'], 'sort': ['price_up_1d']}, 'show_recently_price': True}
body_file = r'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard\_body.json'
import json
with open(body_file, 'w', encoding='utf-8') as f:
    json.dump(body, f, ensure_ascii=False)

result = subprocess.run(
    ['python', r'C:\Users\Lenovo\.qclaw\workspace\skills\csqaq-market-lookup\scripts\csqaq_api.py', 'call',
     '--path', '/api/v1/info/get_rank_list', '--method', 'POST', '--body-file', body_file],
    capture_output=True, timeout=60
)

raw = result.stdout
# 找到 JSON 部分的字节（跳过 [CALL] 和 [STATUS] 行）
# 先用 latin-1 找到 JSON 起始位置
text_latin = raw.decode('latin-1')
json_offset = -1
for line in text_latin.split('\n'):
    if line.startswith('[CALL]') or line.startswith('[STATUS]'):
        continue
    if line.startswith('{') or line.startswith('['):
        json_offset = text_latin.index(line)
        break

if json_offset >= 0:
    json_bytes = raw[json_offset:]
    # 直接保存原始字节
    with open(r'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard\_raw_bytes.json', 'wb') as f:
        f.write(json_bytes)
    
    # 尝试两种解码
    for enc in ['utf-8', 'gbk', 'cp936']:
        try:
            text = json_bytes.decode(enc)
            data = json.loads(text)
            items = data.get('data', {}).get('data', [])
            name = items[0]['name'] if items else 'N/A'
            with open(r'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard\_' + enc + '_result.json', 'w', encoding='utf-8') as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            # 写到文件避免 print 编码问题
            with open(r'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard\_test_log.txt', 'a', encoding='utf-8') as f:
                f.write(f"[{enc}] items={len(items)}, first_name={name}\n")
        except Exception as e:
            with open(r'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard\_test_log.txt', 'a', encoding='utf-8') as f:
                f.write(f"[{enc}] FAILED: {e}\n")
