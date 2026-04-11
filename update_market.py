import http.client, ssl, json, subprocess, time
from datetime import datetime, timezone, timedelta
from collections import defaultdict

ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def fetch_json_stdt(path):
    c = http.client.HTTPSConnection("api.steamdt.com", context=ctx, timeout=15)
    c.request("GET", path, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://steamdt.com/"})
    r = c.getresponse()
    data = json.loads(r.read())
    c.close()
    return data.get("data", data)

def fetch_json_csqaq(path):
    c = http.client.HTTPSConnection("api.csqaq.com", context=ctx, timeout=20)
    c.request("GET", path, headers={"ApiToken": "HXGPY1R7L5W7K7F3O4K1E2N8", "User-Agent": "Mozilla/5.0"})
    r = c.getresponse()
    data = json.loads(r.read())
    c.close()
    return data.get("data", data)

# 1. SteamDT summary + transaction trend
summary      = fetch_json_stdt("/index/statistics/v1/summary")
stdt_daily   = fetch_json_stdt("/index/transaction/trend/v1/all")

today_close  = float(summary.get("broadMarketIndex", 0))
yest_ratio   = float(summary.get("diffYesterdayRatio", 0))
yest_close   = today_close / (1 + yest_ratio / 100.0) if yest_ratio else today_close

print(f"SteamDT today: {today_close}, yest: {yest_close}, ratio: {yest_ratio}")

# 2. CSQAQ 日线（备用：如果限流就用 market.json 里的旧数据）
csqaq_daily = None
try:
    csqaq_daily = fetch_json_csqaq("/api/v1/sub/kline?type=1day&id=1&maxTime=")
    if csqaq_daily and len(csqaq_daily) > 0:
        print(f"CSQAQ daily: {len(csqaq_daily)} bars")
except Exception as e:
    print(f"CSQAQ daily ERR: {e}")
    csqaq_daily = None

# 3. 如果 CSQAQ 没数据，用 SteamDT transaction trend 反推价格
# transaction trend 格式: [[date, turnover, count], ...]
# 策略: 用 yest_close 和 today_close 做基准，中间日期线性插值

# 生成日期-成交额映射
stdt_turnover = {}
stdt_count    = {}
for item in stdt_daily:
    stdt_turnover[item[0]] = float(item[1])
    stdt_count[item[0]]    = float(item[2])

# 4. 用 SteamDT 的 historyMarketIndexList（小时线）聚合日线 OHLC
hist_hourly = summary.get("historyMarketIndexList", [])
daily_ohlc_stdt = defaultdict(list)
for item in hist_hourly:
    ts, price = int(item[0]), float(item[1])
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    key = dt.strftime("%Y-%m-%d")
    daily_ohlc_stdt[key].append(price)

# 聚合
daily_stdt_ohlc = {}
for date_s, prices in daily_ohlc_stdt.items():
    daily_stdt_ohlc[date_s] = {
        "open":  prices[0],
        "high":  max(prices),
        "low":   min(prices),
        "close": prices[-1],
    }

print(f"SteamDT 小时聚合日K: {list(daily_stdt_ohlc.keys())}")

# 5. 生成日K数据
dates  = []
values = []
ohlc   = []
volBar = []
volColor = []

if csqaq_daily and len(csqaq_daily) > 10:
    # 用 CSQAQ 日线价格（乘以比例因子转 SteamDT 指数）
    csq_today = float(csqaq_daily[-1][4]) if isinstance(csqaq_daily[-1], list) else float(csqaq_daily[-1].get("c", 0))
    ratio = today_close / csq_today if csq_today else 1.0

    for item in csqaq_daily:
        if isinstance(item, list) and len(item) >= 5:
            ts_ms    = int(item[0])
            csq_o    = float(item[1])
            csq_h    = float(item[2])
            csq_l    = float(item[3])
            csq_c    = float(item[4])
        else:
            continue

        dt     = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        date_s = dt.strftime("%Y-%m-%d")

        dates.append(date_s[5:])
        values.append(round(csq_c * ratio, 2))

        stdt_tov = stdt_turnover.get(date_s, 0)
        stdt_cnt = int(stdt_count.get(date_s, 0))

        ohlc.append({
            "date":     date_s[5:],
            "open":     round(csq_o * ratio, 2),
            "high":     round(csq_h * ratio, 2),
            "low":      round(csq_l * ratio, 2),
            "close":    round(csq_c * ratio, 2),
            "volume":   stdt_cnt if stdt_cnt > 0 else 0,
            "turnover": round(stdt_tov, 2) if stdt_tov > 0 else 0,
        })
else:
    # 降级：用 SteamDT transaction trend + 小时线
    for item in stdt_daily:
        date_s = item[0]
        turnover = float(item[1])
        count    = float(item[2])

        dp = daily_stdt_ohlc.get(date_s)
        if dp:
            index_val = dp["close"]
            op = dp["open"]
            hp = dp["high"]
            lp = dp["low"]
        else:
            index_val = values[-1] if values else today_close
            op = hp = lp = index_val

        dates.append(date_s[5:])
        values.append(round(index_val, 2))
        ohlc.append({
            "date":     date_s[5:],
            "open":     round(op, 2),
            "high":     round(hp, 2),
            "low":      round(lp, 2),
            "close":    round(index_val, 2),
            "volume":   int(count),
            "turnover": round(turnover, 2),
        })

# volBar / volColor
max_vol = max((d.get("volume", 1) for d in ohlc), default=1) or 1
for i, o in enumerate(ohlc):
    bar_h = max(20, round(o.get("volume", 0) / max_vol * 150))
    volBar.append(bar_h)
    prev_close = values[i-1] if i > 0 else values[0]
    volColor.append('#ef4444' if values[i] >= prev_close else '#22c55e')

# 6. 最新值
lt  = values[-1] if values else 0
pv  = values[-2] if len(values) > 1 else lt
chg = round((lt - pv) / pv * 100, 2) if pv else 0

print(f"\n数据验证:")
print(f"  最新指数: {lt} (涨跌: {chg}%)")
print(f"  最新日K: {ohlc[-1] if ohlc else None}")
print(f"  最新成交量: {ohlc[-1].get('volume', 0):,}")
print(f"  最新成交额: {ohlc[-1].get('turnover', 0):,.2f}")
print(f"  价格样本 (最近5天): {values[-5:]}")

# 7. 写入 market.json
mjp = r"C:\Users\Lenovo\cs2-dashboard\market.json"
with open(mjp, "r", encoding="utf-8") as f:
    mj = json.load(f)

mj["index"] = {
    "latest":   round(lt, 2),
    "change":   chg,
    "dates":    dates,
    "values":   values,
    "min":      round(min(values), 2),
    "max":      round(max(values), 2),
    "ohlc":     ohlc,
    "volBar":   volBar,
    "volColor": volColor,
    "todayStats": {
        "turnover": round(float(summary.get("todayStatistics", {}).get("turnover") or 0), 2),
        "count":    int(summary.get("todayStatistics", {}).get("tradeNum") or 0),
    },
    "yesterdayStats": {
        "turnover": round(float(summary.get("yesterdayStatistics", {}).get("turnover") or 0), 2),
        "count":    int(summary.get("yesterdayStatistics", {}).get("tradeNum") or 0),
    },
    "surviveNum": int(summary.get("surviveNum") or 0),
    "holdersNum": int(summary.get("holdersNum") or 0),
}

with open(mjp, "w", encoding="utf-8") as f:
    json.dump(mj, f, ensure_ascii=False, indent=2)

print(f"\nmarket.json 写入: {len(ohlc)} 根日K")

# 8. Git push
repo = r"C:\Users\Lenovo\cs2-dashboard"
subprocess.run(["git", "-C", repo, "add", "."], check=True, capture_output=True)
r2 = subprocess.run(["git", "-C", repo, "commit", "-m",
    "feat: CSQAQ daily OHLC x SteamDT real turnover"],
    capture_output=True)
print(f"Commit: {'OK' if r2.returncode == 0 else r2.stderr}")
r3 = subprocess.run(["git", "-C", repo, "push"], capture_output=True)
print(f"Push: {'OK' if r3.returncode == 0 else r3.stderr}")
