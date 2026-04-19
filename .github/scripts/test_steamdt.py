"""测试 SteamDT K线 API —— 验证返回值结构和 volume 字段"""
import urllib.request
import json
import os
import datetime
import urllib.parse

API_KEY = os.environ.get("STEAMDT_KEY", "fb73ba391b4542a1bd182d92a93f10d4")
KLINE_URL = "https://open.steamdt.com/open/cs2/item/v1/kline"
PRICE_URL = "https://open.steamdt.com/open/cs2/v1/price/single"

items = [
    "AK-47 | Redline (Field-Tested)",
    "AWP | Asiimov (Field-Tested)",
]

results = {"timestamp": datetime.datetime.now().isoformat(), "STEAMDT_KEY_prefix": API_KEY[:8] + "***", "items": {}}

print("=== SteamDT K线测试 ===")
print(f"API Key prefix: {API_KEY[:8]}***")

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
                msg = f"ERROR: {d.get('errorMsg', '')}"
                print(msg)
                results["items"][name] = {"error": msg}
                continue
            data = d.get("data") or []
            has_volume = len(data[0]) == 6 if data else False
            print(f"  条目: {len(data)}, 字段数: {len(data[0]) if data else 0}")
            print(f"  最新: {data[0] if data else 'N/A'}")
            item_result = {
                "count": len(data),
                "fields": len(data[0]) if data else 0,
                "has_volume": has_volume,
                "latest": data[0] if data else None,
                "sample": data[:3] if data else []
            }
            print(f"  has_volume: {has_volume}")
            results["items"][name] = item_result
    except Exception as e:
        print(f"  ERROR: {e}")
        results["items"][name] = {"error": str(e)}

print("\n=== SteamDT Price 测试 ===")
for name in items[:1]:
    encoded_name = urllib.parse.quote(name)
    url = f"{PRICE_URL}?marketHashName={encoded_name}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read())
            if d.get("success"):
                platforms = d.get("data") or []
                print(f"[{name}]")
                print(f"  平台数: {len(platforms)}")
                for p in platforms:
                    print(f"  {p['platform']}: sellPrice={p['sellPrice']} sellCount={p['sellCount']} biddingCount={p['biddingCount']}")
                results["price"] = {"name": name, "platforms": len(platforms), "data": platforms[:3]}
    except Exception as e:
        print(f"  ERROR: {e}")
        results["price"] = {"error": str(e)}

# Write results to file
output_path = os.environ.get("GITHUB_OUTPUT", "/tmp/steamdt_test_result.json")
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\n=== 结果已写入: {output_path} ===")
print(json.dumps(results, ensure_ascii=False, indent=2))
