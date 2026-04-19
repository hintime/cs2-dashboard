"""测试 SteamDT K线 API —— 验证返回值结构和 volume 字段"""
import urllib.request
import json
import os

API_KEY = os.environ.get("STEAMDT_KEY", "fb73ba391b4542a1bd182d92a93f10d4")
URL = "https://open.steamdt.com/open/cs2/v1/kline"

body = json.dumps({
    "marketHashName": "AK-47 | Redline (Field-Tested)",
    "type": 2
}).encode()

req = urllib.request.Request(
    URL,
    data=body,
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    },
    method="POST"
)

try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
        print(f"HTTP {resp.status}, size={len(raw)} bytes")
        d = json.loads(raw)
        print("success:", d.get("success"))
        print("errorCode:", d.get("errorCode"), d.get("errorMsg", ""))
        data = d.get("data")
        print(f"data type: {type(data).__name__}")
        if isinstance(data, list):
            print(f"entries count: {len(data)}")
            for i, item in enumerate(data[:5]):
                print(f"  [{i}] len={len(item)}: {item}")
        elif isinstance(data, dict):
            print(f"keys: {list(data.keys())[:15]}")
            for k in list(data.keys())[:5]:
                print(f"  [{k}]: {data[k]}")
        elif data is None:
            print("data is null (no volume available)")
except Exception as e:
    print(f"ERROR: {e}")
