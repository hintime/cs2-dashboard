"""测试 SteamDT K线 API —— 验证返回值结构和 volume 字段"""
import urllib.request
import json
import os

API_KEY = os.environ.get("STEAMDT_KEY", "fb73ba391b4542a1bd182d92a93f10d4")
KLINE_URL = "https://open.steamdt.com/open/cs2/item/v1/kline"
PRICE_URL = "https://open.steamdt.com/open/cs2/v1/price/single"

items = [
    "AK-47 | Redline (Field-Tested)",
    "AWP | Asiimov (Field-Tested)",
    "M4A4 | Howl (Factory New)",
]

print("=== SteamDT K线测试 ===")
for name in items:
    print(f"\n[{name}]")
    body = json.dumps({"marketHashName": name, "type": 2}).encode()
    req = urllib.request.Request(
        KLINE_URL, data=body,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read())
            if not d.get("success"):
                print(f"  ERROR: {d.get('errorMsg', '')}")
                continue
            data = d.get("data") or []
            print(f"  K线条目: {len(data)}")
            if data:
                print(f"  最新: {data[0]}")
                print(f"  字段数: {len(data[0])}")
                print(f"  字段含义: [timestamp, open, close, high, low]")
                if len(data[0]) == 6:
                    print(f"  ⚠️ 6字段(含volume!): {data[0]}")
                else:
                    print(f"  ⚠️ 无volume字段 (只有{len(data[0])}字段)")
    except Exception as e:
        print(f"  ERROR: {e}")

print("\n=== SteamDT Price 测试（看有无成交量）===")
for name in items[:1]:
    url = f"{PRICE_URL}?marketHashName={name}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read())
            if d.get("success"):
                platforms = d.get("data") or []
                print(f"[{name}]")
                for p in platforms:
                    print(f"  {p['platform']}: sellPrice={p['sellPrice']} sellCount={p['sellCount']} biddingPrice={p['biddingPrice']} biddingCount={p['biddingCount']}")
    except Exception as e:
        print(f"  ERROR: {e}")
