#!/usr/bin/env python3
import os, json, time, traceback
from datetime import datetime as dt, timezone

STEAM_KEY = os.environ.get("STEAMDT_KEY", "")
CSQ_KEY = "HXGPY1R7L5W7K7F3O4K1E2N8"
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = "hintime/cs2-dashboard"

def log(msg):
    print("[" + dt.now().strftime("%H:%M:%S") + "] " + str(msg), flush=True)

log("GITHUB_TOKEN len: " + str(len(GH_TOKEN)))
log("STEAMDT_KEY len: " + str(len(STEAM_KEY)))

# ===== CSQAQ Test (show raw response) =====
log("=== CSQAQ Raw Response Test ===")
import urllib.request as ur
CSQ_BASE = "https://api.csqaq.com/api/v1"
body = json.dumps({"page_index":1,"page_size":5,"filter":{"type":["sticker","normal"],"sort":["price_up_1d"]},"show_recently_price":True}).encode()
req = ur.Request(CSQ_BASE+"/info/get_rank_list",
    data=body, method="POST",
    headers={"ApiToken": CSQ_KEY, "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
try:
    with ur.urlopen(req, timeout=15) as r:
        raw = r.read()
        raw_text = raw.decode("utf-8", errors="replace")
        log("CSQAQ raw[:300]: " + raw_text[:300])
        d = json.loads(raw_text)
        data = d.get("data")
        log("CSQAQ data type: " + str(type(data)))
        if isinstance(data, dict):
            inner = data.get("data")
            log("CSQAQ inner count: " + str(len(inner) if inner else 0))
            if inner:
                log("First item: " + str(inner[0].get("name","?"))[:80])
        else:
            log("CSQAQ d.keys: " + str(list(d.keys())))
except Exception as e:
    log("CSQAQ error: " + str(e) + " | " + traceback.format_exc()[:200])

# ===== SteamDT Kline Test =====
log("=== SteamDT Kline Test ===")
STEAM_BASE = "https://open.steamdt.com"
kbody = json.dumps({"marketHashName": "AK-47 | Redline (Field-Tested)", "type": 2}).encode()
kreq = ur.Request(STEAM_BASE+"/open/cs2/item/v1/kline",
    data=kbody, method="POST",
    headers={"Authorization": "Bearer "+STEAM_KEY, "Content-Type": "application/json"})
try:
    with ur.urlopen(kreq, timeout=15) as kr:
        raw = kr.read()
        raw_text = raw.decode("utf-8", errors="replace")
        d = json.loads(raw_text)
        log("SteamDT kline success: " + str(d.get("success")))
        log("SteamDT kline err: " + str(d.get("errorCode")) + " " + str(d.get("errorMsg","")))
        if d.get("data"):
            vals = list(d["data"].values()) if isinstance(d["data"], dict) else d["data"]
            log("SteamDT kline pts: " + str(len(vals)))
        else:
            log("SteamDT kline data: " + str(d.get("data"))[:100])
except Exception as e:
    log("SteamDT error: " + str(e))

log("Done!")
