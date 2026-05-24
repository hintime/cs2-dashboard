"""测试 SteamDT API —— 全接口连通性检查"""
import urllib.request
import urllib.error
import json
import os
import urllib.parse

API_KEY = os.environ.get("STEAMDT_KEY", "")
BASE = "https://open.steamdt.com"
ITEM = "AK-47 | Redline (Field-Tested)"

print(f"API Key prefix: {API_KEY[:8]}***")
print(f"Base URL: {BASE}\n")

def call(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    headers = {"Authorization": f"Bearer {API_KEY}"}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            d = json.loads(raw)
            ok = d.get("success", False)
            err = d.get("errorMsg", "") or d.get("errorCode", "")
            print(f"  [{method} {path}] success={ok} err={err}")
            if ok:
                data_val = d.get("data")
                if isinstance(data_val, list):
                    print(f"    -> list len={len(data_val)}, first={json.dumps(data_val[0])[:120] if data_val else 'empty'}")
                elif isinstance(data_val, dict):
                    print(f"    -> dict keys={list(data_val.keys())[:8]}")
                else:
                    print(f"    -> {str(data_val)[:120]}")
            return d
    except urllib.error.HTTPError as e:
        body_err = e.read().decode("utf-8", errors="replace")[:200]
        print(f"  [{method} {path}] HTTP {e.code}: {body_err}")
        return None
    except Exception as e:
        print(f"  [{method} {path}] ERROR: {e}")
        return None

print("=== 1. K线接口 ===")
call("POST", "/open/cs2/item/v1/kline", {"marketHashName": ITEM, "type": 2})
call("POST", "/open/cs2/v1/kline", {"marketHashName": ITEM, "type": 2})

print("\n=== 2. 单品价格接口 ===")
encoded = urllib.parse.quote(ITEM)
call("GET", f"/open/cs2/v1/price/single?marketHashName={encoded}")

print("\n=== 3. 批量价格接口 ===")
call("POST", "/open/cs2/v1/price/batch", {"marketHashNames": [ITEM]})

print("\n=== 4. 7日均价接口 ===")
call("GET", f"/open/cs2/v1/price/avg?marketHashName={encoded}")

print("\n=== 5. 基础信息接口 ===")
call("GET", "/open/cs2/v1/base")

print("\n=== Done ===")
