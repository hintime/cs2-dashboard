#!/usr/bin/env python3
"""Fetch CSQAQ alerts + SteamDT K-lines and push to market.json"""
import urllib.request, urllib.parse, json, ssl, base64, time, os, socket
from datetime import datetime, timezone

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

CSQ_KEY = "HXGPY1R7L5W7K7F3O4K1E2N8"
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
STEAM_KEY = os.environ.get("STEAMDT_KEY", "")
REPO = "hintime/cs2-dashboard"

def log(msg):
    print("[ok] " + str(msg), flush=True)

def steamdt_request(path, body=None):
    """Make request to SteamDT API"""
    url = f"https://open.steamdt.com{path}"
    headers = {
        "Authorization": f"Bearer {STEAM_KEY}",
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json"
    }
    if body:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    else:
        req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"success": False, "errorMsg": str(e)}

# --- IP 检测 ---
log("=== CI Runner IP 检测 ===")
try:
    req_ip = urllib.request.Request("https://api.ipify.org", headers={"User-Agent": "curl/7.68.0"})
    with urllib.request.urlopen(req_ip, timeout=10, context=ctx) as r:
        ip = r.read().decode().strip()
        log(f"CI Runner IP: {ip}")
except Exception as e:
    log(f"IP 检测失败: {e}")

# --- SteamDT K-lines ---
log("Fetching SteamDT K-lines...")
ITEMS = [
    "AK-47 | Redline (Field-Tested)",
    "AWP | Asiimov (Field-Tested)",
    "M4A4 | Asiimov (Battle-Scarred)",
    "M4A1-S | Mecha-Industries (Field-Tested)",
    "USP-S | Kill Confirmed (Field-Tested)",
    "Glock-18 | Fade (Factory New)"
]

kline_data = {}
for name in ITEMS:
    log(f"  K-line: {name[:30]}...")
    resp = steamdt_request("/open/cs2/item/v1/kline", {
        "marketHashName": name,
        "type": 2,
        "platform": "BUFF"
    })
    log(f"    -> raw resp keys: {list(resp.keys())} errorCode={resp.get('errorCode')}")
    if resp.get("success"):
        raw = resp.get("data", [])
        # data is flat array of [ts, open, close, high, low] — 5 elements each
        parsed = []
        if raw and isinstance(raw, list):
            for p in raw:
                if isinstance(p, list) and len(p) >= 5:
                    parsed.append([int(p[0]), float(p[1]), float(p[2]), float(p[3]), float(p[4]), 0])
        kline_data[name] = parsed
        log(f"    -> {len(parsed)} points")
    else:
        log(f"    -> SteamDT failed: code={resp.get('errorCode')} msg={resp.get('errorMsg')} str={resp.get('errorCodeStr')}")

# --- SteamDT prices ---
log("Fetching SteamDT prices...")
price_data = {}
for name in ITEMS:
    resp = steamdt_request(f"/open/cs2/v1/price/single?app_id=730&marketHashName={urllib.parse.quote(name)}")
    if resp.get("success"):
        data = resp.get("data", [])
        if data:
            # Find BUFF price
            for p in data:
                if p.get("platform") == "BUFF":
                    price_data[name] = {
                        "price": p.get("sellPrice", 0),
                        "count": p.get("sellCount", 0)
                    }
                    log(f"  {name[:30]}: ¥{p.get('sellPrice', 0)}")
                    break

# --- CSQAQ 异动数据 ---
log("Fetching CSQAQ alerts...")
all_alerts = []
for page in range(1, 5):
    body = json.dumps({
        "page_index": page, "page_size": 25,
        "filter": {"type": ["sticker", "normal"], "sort": ["price_up_1d"]},
        "show_recently_price": True
    }).encode()
    req = urllib.request.Request(
        "https://api.csqaq.com/api/v1/info/get_rank_list",
        data=body, method="POST",
        headers={"ApiToken": CSQ_KEY, "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            raw = r.read()
            d = json.loads(raw.decode("utf-8"))
            inner = d.get("data", {})
            items = (inner.get("data") if isinstance(inner, dict) else inner) or []
            if not items:
                break
            for item in items:
                rate_1 = item.get("sell_price_rate_1", 0) or 0
                rate_7 = item.get("sell_price_rate_7", 0) or 0
                rate_30 = item.get("sell_price_rate_30", 0) or 0
                all_alerts.append({
                    "id": item.get("id"),
                    "name": item.get("name", ""),
                    "rate_1": round(float(rate_1), 2),
                    "rate_7": round(float(rate_7), 2),
                    "rate_30": round(float(rate_30), 2),
                    "price": item.get("buff_sell_price") or 0,
                    "buff_price_chg": item.get("buff_price_chg", 0) or 0,
                    "img": item.get("img", ""),
                    "exterior": item.get("exterior_localized_name", ""),
                    "rarity": item.get("rarity_localized_name", ""),
                    "rank_num": item.get("rank_num", 0) or 0,
                })
        log(f"CSQAQ page {page}: total={len(all_alerts)}")
        if len(items) < 25:
            break
    except Exception as e:
        log(f"CSQAQ page {page} failed: {e}")
        # Also try to read error body
        if hasattr(e, 'read'):
            try:
                body = e.read()
                log(f"  CSQAQ error body: {body.decode('utf-8', errors='replace')[:200]}")
            except:
                pass
    time.sleep(1.2)

log(f"CSQAQ alerts: {len(all_alerts)}")

# --- Load and update market.json ---
req_mj = urllib.request.Request(
    f"https://api.github.com/repos/{REPO}/contents/market.json?ref=main",
    headers={"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json"}
)
with urllib.request.urlopen(req_mj, context=ctx, timeout=10) as r:
    mj_data = json.loads(r.read().decode())
    mj_content = json.loads(base64.b64decode(mj_data["content"]).decode("utf-8"))

# Update alerts
mj_content["alerts"] = all_alerts
mj_content["alerts_updated"] = datetime.now(timezone.utc).isoformat()

# Update items with K-lines and prices
items_list = mj_content.get("items", [])
for item in items_list:
    name = item.get("name", "")
    if name in kline_data:
        item["kline"] = kline_data[name]
    if name in price_data:
        item["price"] = price_data[name]["price"]
        item["count"] = price_data[name]["count"]

mj_content["items"] = items_list
mj_content["items_updated"] = datetime.now(timezone.utc).isoformat()

log(f"Items with K-lines: {sum(1 for i in items_list if i.get('kline'))}")

# --- Push to GitHub ---
new_content = base64.b64encode(
    json.dumps(mj_content, ensure_ascii=False, indent=2).encode("utf-8")
).decode()

sha = mj_data["sha"]
req_push = urllib.request.Request(
    f"https://api.github.com/repos/{REPO}/contents/market.json",
    data=json.dumps({"message": "update: K-lines + alerts", "content": new_content, "sha": sha, "branch": "main"}).encode("utf-8"),
    method="PUT",
    headers={"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json", "Content-Type": "application/json"}
)
try:
    with urllib.request.urlopen(req_push, context=ctx, timeout=10) as r:
        result = json.loads(r.read().decode())
        log("Pushed: " + str(result.get("commit", {}).get("html_url", "?")))
except Exception as e:
    log(f"Push failed: {e}")

log(f"Done! alerts={len(all_alerts)}, items={len(items_list)}")
