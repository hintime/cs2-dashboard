import urllib.request
import json

tokens = [
    "HXGPY1R7L5W7K7F3O4K1E2N8",
    "csqaqapi_HXGPY1R7L5W7K7F3O4K1E2N8"
]

url = "https://api.csqaq.com/api/v1/info/get_rank_list"
body = json.dumps({"page_index": 1, "page_size": 5}).encode('utf-8')

for token in tokens:
    print(f"\n=== Token: {token} ===")
    headers = {"ApiToken": token, "Content-Type": "application/json"}
    try:
        req = urllib.request.Request(url, data=body, method="POST", headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            for enc in ['gbk', 'utf-8']:
                try:
                    text = raw.decode(enc)
                    data = json.loads(text)
                    print(f"[{enc}] OK! code={data.get('code')} msg={data.get('msg')}")
                    break
                except:
                    pass
    except urllib.error.HTTPError as e:
        raw = e.read()
        for enc in ['utf-8', 'gbk']:
            try:
                text = raw.decode(enc)
                print(f"HTTP {e.code} [{enc}]: {text[:300]}")
                break
            except:
                pass
    except Exception as e:
        print(f"Error: {e}")
