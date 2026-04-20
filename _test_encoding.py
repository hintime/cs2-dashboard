import urllib.request
import json

url = "https://api.csqaq.com/api/v1/info/get_rank_list"
body = json.dumps({"page_index": 1, "page_size": 3, "filter": {"type": ["sticker", "normal"], "sort": ["price_up_1d"]}, "show_recently_price": True}).encode('utf-8')
headers = {"ApiToken": "HXGPY1R7L5W7K7F3O4K1E2N8", "Content-Type": "application/json"}

req = urllib.request.Request(url, data=body, method="POST", headers=headers)
with urllib.request.urlopen(req, timeout=30) as resp:
    raw = resp.read()
    # 写入文件用 UTF-8 保存结果
    text = raw.decode('utf-8')
    data = json.loads(text)
    items = data.get('data', {}).get('data', [])
    
    # 写到文件避免 PowerShell 编码问题
    with open(r'C:\Users\Lenovo\.qclaw\workspace\cs2-dashboard\_api_result.json', 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print(f"OK - {len(items)} items saved to _api_result.json")
