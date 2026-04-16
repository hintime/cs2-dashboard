#!/usr/bin/env python3
"""CS2 Dashboard 数据更新 - 纯标准库 urllib"""
import os, json, time, base64, urllib.request, ssl
from datetime import datetime as dt, timezone

STEAM_KEY = "fb73ba391b4542a1bd182d92a93f10d4"
STEAM_BASE = "https://open.steamdt.com"
CSQ_KEY = "HXGPY1R7L5W7K7F3O4K1E2N8"
CSQ_BASE = "https://api.csqaq.com/api/v1"
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = "hintime/cs2-dashboard"
API = "https://api.github.com/repos/" + REPO + "/contents/market.json"

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def log(msg):
    print("[" + dt.now().strftime("%H:%M:%S") + "] " + str(msg), flush=True)

def post(url, body, headers=None):
    data = json.dumps(body).encode("utf-8")
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
        return r.read()

def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
        return r.read()

log("Token: " + str(len(GH_TOKEN) > 0))

# ===大盘指数===
market_index = {}
try:
    raw = get(CSQ_BASE + "/market/summary", {"ApiToken": CSQ_KEY})
    try:
        text = raw.decode("gbk")
    except:
        text = raw.decode("utf-8", errors="replace")
    d = json.loads(text)
    if d.get("data"):
        market_index = d["data"]
        log("market_index OK: " + str(list(d["data"].keys())[:3]))
    else:
        log("market_index msg: " + d.get("msg", ""))
except Exception as e:
    log("market_index failed: " + str(e))

# ===K线===
TRACKED = [
    ("AK-47 | Redline (Field-Tested)", "AK-47 Redline FT"),
    ("AWP | Asiimov (Field-Tested)", "AWP Asiimov FT"),
    ("M4A4 | Asiimov (Battle-Scarred)", "M4A4 Asiimov BS"),
    ("M4A1-S | Mecha-Industries (Field-Tested)", "M4A1-S Mecha FT"),
    ("USP-S | Kill Confirmed (Field-Tested)", "USP-S KillConfirmed FT"),
    ("Glock-18 | Fade (Factory New)", "Glock-18 Fade FN"),
]
items = {}
for name_en, name_cn in TRACKED:
    log("Kline: " + name_cn)
    kline = []
    try:
        raw = post(
            STEAM_BASE + "/open/cs2/item/v1/kline",
            {"marketHashName": name_en, "type": 2},
            {"Authorization": "Bearer " + STEAM_KEY}
        )
        d = json.loads(raw.decode("utf-8", errors="replace"))
        if d.get("success"):
            raw_data = d.get("data", {})
            vals = list(raw_data.values()) if isinstance(raw_data, dict) else (raw_data if isinstance(raw_data, list) else [])
            for k in vals:
                if isinstance(k, list) and len(k) >= 5:
                    kline.append({"ts": int(k[0]), "open": float(k[1]), "high": float(k[3]), "low": float(k[4]), "close": float(k[2]), "vol": 0})
            log("  Kline " + str(len(kline)) + " pts")
        else:
            log("  SteamDT Kline fail: " + str(d.get("errorMsg")) + " | " + str(d.get("errorData")))
    except Exception as e:
        log("  SteamDT error: " + str(e))
    if kline:
        latest = kline[-1]
        prev = kline[-2] if len(kline) > 1 else latest
        chg = ((latest["close"] - prev["close"]) / prev["close"] * 100) if prev["close"] else 0
        items[name_en] = {"name_cn": name_cn, "name_en": name_en, "latest": latest["close"], "change": round(chg, 2), "kline": kline}
    time.sleep(0.5)
log("Items: " + str(len(items)))

# ===异动数据===
all_items = {}
for _try in range(2):
    for page in range(1, 3):
        body = {"page_index": page, "page_size": 50,
            "filter": {"type": ["sticker", "normal"], "sort": ["price_up_1d"]},
            "show_recently_price": True}
        try:
            raw = post(CSQ_BASE + "/info/get_rank_list", body, {"ApiToken": CSQ_KEY})
            try:
                text = raw.decode("gbk")
            except:
                text = raw.decode("utf-8", errors="replace")
            d = json.loads(text)
            for item in d.get("data", {}).get("data", []):
                n = item.get("name", "").strip()
                if n and n not in all_items:
                    all_items[n] = item
            time.sleep(1.2)
        except Exception as e:
            log("  CSQAQ page " + str(page) + " error: " + str(e))
log("Rank items: " + str(len(all_items)))

alerts = []
for name, item in all_items.items():
    alerts.append({
        "id": item.get("id", 0), "name": name,
        "exterior": item.get("exterior_localized_name", ""),
        "rarity": item.get("rarity_localized_name", ""),
        "price": float(item.get("buff_sell_price") or 0),
        "price_1": float(item.get("recently_price_1") or 0),
        "price_7": float(item.get("recently_price_7") or 0),
        "rate_1": float(item.get("buff_price_chg") or 0),
        "rate_7": float(item.get("sell_price_rate_7") or 0),
        "rank_num": item.get("rank_num", 0),
        "statistic": item.get("statistic", 0),
        "img": item.get("img", ""),
        "updated": item.get("updated", "")})
alerts.sort(key=lambda x: x.get("rate_1", 0), reverse=True)

# ===合并写入===
with open("market.json", "r", encoding="utf-8") as f:
    market = json.load(f)
market["market_index"] = market_index
market["items"] = items
market["alerts"] = alerts
now_utc = dt.now(timezone.utc).isoformat().replace("+00:00", "Z")
market["items_updated"] = now_utc
market["alerts_updated"] = now_utc
with open("market.json", "w", encoding="utf-8") as f:
    json.dump(market, f, ensure_ascii=False, indent=2)
log("Written: items=" + str(len(items)) + " alerts=" + str(len(alerts)))

# ===推送GitHub===
if GH_TOKEN:
    content = json.dumps(market, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(content.encode("utf-8")).decode()
    sha = None
    try:
        req_sha = urllib.request.Request(API + "?ref=main",
            headers={"Authorization": "Bearer " + GH_TOKEN, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req_sha, context=ctx, timeout=10) as r:
            sha = json.loads(r.read().decode())["sha"]
    except Exception as e:
        log("Get SHA: " + str(e))
    body = {"message": "chore: update market data (" + dt.now().strftime("%m-%d %H:%M") + ")",
        "content": encoded, "branch": "main"}
    if sha:
        body["sha"] = sha
    req2 = urllib.request.Request(API, data=json.dumps(body).encode("utf-8"), method="PUT",
        headers={"Authorization": "Bearer " + GH_TOKEN, "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req2, context=ctx, timeout=10) as r:
            result = json.loads(r.read().decode())
            log("Pushed: " + str(result.get("commit", {}).get("html_url", "")))
    except Exception as e:
        log("Push failed: " + str(e))
else:
    log("No GITHUB_TOKEN")
log("Done!")
