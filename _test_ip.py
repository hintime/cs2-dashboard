import urllib.request
import json

url = "https://api.csqaq.com/api/v1/info/get_rank_list"
body = json.dumps({"page_index": 1, "page_size": 5, "filter": {"type": ["sticker", "normal"], "sort": ["price_up_1d"]}, "show_recently_price": True}).encode('utf-8')
headers = {"ApiToken": "HXGPY1R7L5W7K7F3O4K1E2N8", "Content-Type": "application/json"}

req = urllib.request.Request(url, data=body, method="POST", headers=headers)
with urllib.request.urlopen(req, timeout=30) as resp:
    raw = resp.read()
    for enc in ['gbk', 'utf-8']:
        try:
            text = raw.decode(enc)
            data = json.loads(text)
            print(f"[{enc}] code={data.get('code')} msg={data.get('msg')}")
            items = data.get('data', {}).get('data', [])
            if items:
                print(f"Items: {len(items)}")
                print(f"First: {items[0].get('name', 'N/A')}")
            break
        except Exception as e:
            print(f"[{enc}] failed: {e}")
