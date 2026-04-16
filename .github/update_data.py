#!/usr/bin/env python3
import os, json, time
from datetime import datetime as dt, timezone

# API keys
STEAM_KEY = os.environ.get("STEAMDT_KEY", "fb73ba391b4542a1bd182d92a93f10d4")
CSQ_KEY = "HXGPY1R7L5W7K7F3O4K1E2N8"

import requests

STEAM_BASE = "https://open.steamdt.com"
CSQ_BASE = "https://api.csqaq.com/api/v1"
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = "hintime/cs2-dashboard"
API = "https://api.github.com/repos/" + REPO + "/contents/market.json"

def log(msg):
    print("[" + dt.now().strftime("%H:%M:%S") + "] " + str(msg), flush=True)

log("Token: " + str(len(GH_TOKEN) > 0))
log("STEAMDT_KEY: " + str(len(STEAM_KEY) > 0))

#大盘指数
market_index = {}
try:
    r = requests.get(CSQ_BASE + "/market/summary", headers={"ApiToken": CSQ_KEY}, timeout=10)
    try:
        text = r.content.decode("gbk")
    except:
        text = r.content.decode("utf-8", errors="replace")
    d = r.json()
    if d.get("data"):
        market_index = d["data"]
        log("market_index OK: " + str(list(d["data"].keys())[:3]))
    else:
        log("market_index msg: " + d.get("msg", ""))
except Exception as e:
    log("market_index failed: " + str(e))

#K线
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
        body = {"marketHashName": name_en, "type": 2}
        resp = requests.post(
            STEAM_BASE + "/open/cs2/item/v1/kline",
            json=body,
            headers={"Authorization": "Bearer " + STEAM_KEY},
            timeout=15
        )
        d = resp.json()
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

#异动
all_items = {}
for pg in range(1, 5):
    try:
        body = {"page_index": pg, "page_size": 50,
            "filter": {"type": ["sticker", "normal"], "sort": ["price_up_1d"]},
            "show_recently_price": True}
        r = requests.post(CSQ_BASE + "/info/get_rank_list", json=body, headers={"ApiToken": CSQ_KEY}, timeout=15)
        try:
            text = r.content.decode("gbk")
        except:
            text = r.content.decode("utf-8", errors="replace")
        d = r.json()
        cnt = 0
        for item in d.get("data", {}).get("data", []):
            n = (item.get("name") or "").strip()
            if n and n not in all_items:
                all_items[n] = item
                cnt += 1
        log("CSQAQ page " + str(pg) + ": +" + str(cnt) + " = " + str(len(all_items)))
        time.sleep(1.2)
    except Exception as e:
        log("  CSQAQ page " + str(pg) + " error: " + str(e))

log("CSQAQ total: " + str(len(all_items)))

alerts = []
for name, item in all_items.items():
    alerts.append({
        "id": item.get("id", 0), "name": name,
        "exterior": item.get("exterior_localized_name", ""),
        "rarity": item.get("rarity_localized_name", ""),
        "price": float(item.get("buff_sell_price") or 0),
        "rate_1": float(item.get("buff_price_chg") or 0),
        "rate_7": float(item.get("sell_price_rate_7") or 0),
        "rank_num": item.get("rank_num", 0),
        "img": item.get("img", "")})
alerts.sort(key=lambda x: x.get("rate_1", 0), reverse=True)

#合并写入
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

#推送GitHub
if GH_TOKEN:
    content = json.dumps(market, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(content.encode("utf-8")).decode()
    try:
        from urllib.request import urlopen, Request
        from ssl import create_default_context
        ctx = create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ctx.__class__.__dict__["CERT_NONE"]
        sha_req = Request(API + "?ref=main", headers={"Authorization": "Bearer " + GH_TOKEN, "Accept": "application/vnd.github+json"})
        sha = None
        try:
            with urlopen(sha_req, timeout=10, context=ctx) as r2:
                sha = json.loads(r2.read().decode())["sha"]
        except: pass
        body = {"message": "chore: update market data (" + dt.now().strftime("%m-%d %H:%M") + ")",
            "content": encoded, "branch": "main"}
        if sha: body["sha"] = sha
        req2 = Request(API, data=json.dumps(body).encode("utf-8"), method="PUT",
            headers={"Authorization": "Bearer " + GH_TOKEN, "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json"})
        try:
            with urlopen(req2, timeout=10, context=ctx) as r3:
                result = json.loads(r3.read().decode())
                log("Pushed: " + str(result.get("commit", {}).get("html_url", "")))
        except Exception as e:
            log("Push error: " + str(e))
    except Exception as e:
        log("Import error: " + str(e))
else:
    log("No GITHUB_TOKEN")
log("Done!")
