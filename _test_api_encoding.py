import urllib.request
import json

url = "https://api.csqaq.com/api/v1/info/get_rank_list"
headers = {"ApiToken": "csqaqapi_HXGPY1R7L5W7K7F3O4K1E2N8", "Content-Type": "application/json"}

request = urllib.request.Request(url, method="POST", headers=headers, data=b"{}")
with urllib.request.urlopen(request, timeout=30) as resp:
    raw_bytes = resp.read()
    
# Check encoding
print(f"First 200 bytes (hex): {raw_bytes[:200].hex()}")
print()

# Try different decodings
for enc in ['utf-8', 'gbk', 'gb2312']:
    try:
        decoded = raw_bytes.decode(enc)
        print(f"=== {enc} decoded (first 300 chars) ===")
        print(decoded[:300])
        print()
        
        # Try JSON parse
        try:
            data = json.loads(decoded)
            print(f"[{enc}] JSON parse OK! First item name: {data.get('data', {}).get('data', [{}])[0].get('name', 'N/A') if data.get('data', {}).get('data') else 'N/A'}")
        except:
            print(f"[{enc}] JSON parse FAILED")
    except Exception as e:
        print(f"{enc} decode error: {e}")
