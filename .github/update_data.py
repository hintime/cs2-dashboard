#!/usr/bin/env python3
"""Fetch CSQAQ alerts (UTF-8) and push to market.json"""
import urllib.request, json, ssl, base64, time
from datetime import datetime, timezone

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

CSQ_KEY = "HXGPY1R7L5W7K7F3O4K1E2N8"
STEAM_KEY = ""
GH_TOKEN = ""
REPO = "hintime/cs2-dashboard"

def log(msg):
    print("[ok] " + str(msg), flush=True)

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
    log("page " + str(page) + ": total=" + str(len(all_alerts)))
    if len(items) < 25:
        break
    time.sleep(1.2)

log("CSQAQ alerts: " + str(len(all_alerts)))

# Load market.json
req_mj = urllib.request.Request(
    "https://api.github.com/repos/" + REPO + "/contents/market.json?ref=main",
    headers={"Authorization": "Bearer " + GH_TOKEN, "Accept": "application/vnd.github+json"}
)
with urllib.request.urlopen(req_mj, context=ctx, timeout=10) as r:
    mj_data = json.loads(r.read().decode())
    mj_content = json.loads(base64.b64decode(mj_data["content"]).decode("utf-8"))

mj_content["alerts"] = all_alerts
mj_content["alerts_updated"] = datetime.now(timezone.utc).isoformat()

# Count items with K-line data
items_count = len(mj_content.get("items", []))
log("Existing items (K-lines): " + str(items_count))

new_content = base64.b64encode(
    json.dumps(mj_content, ensure_ascii=False, indent=2).encode("utf-8")
).decode()

sha = mj_data["sha"]
req_push = urllib.request.Request(
    "https://api.github.com/repos/" + REPO + "/contents/market.json",
    data=json.dumps({"message": "fix: CSQAQ alerts UTF-8 decode", "content": new_content, "sha": sha, "branch": "main"}).encode("utf-8"),
    method="PUT",
    headers={"Authorization": "Bearer " + GH_TOKEN, "Accept": "application/vnd.github+json", "Content-Type": "application/json"}
)
with urllib.request.urlopen(req_push, context=ctx, timeout=10) as r:
    result = json.loads(r.read().decode())
    log("Pushed: " + str(result.get("commit", {}).get("html_url", "?")))

log("Done! alerts=" + str(len(all_alerts)))
