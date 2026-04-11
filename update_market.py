import http.client, ssl, json, subprocess
from datetime import datetime, timezone
from collections import defaultdict

ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def fetch(url, host, token=None):
    c = http.client.HTTPSConnection(host, context=ctx, timeout=20)
    h = {"User-Agent": "Mozilla/5.0"}
    if token:
        h["ApiToken"] = token
    else:
        h["Referer"] = "https://steamdt.com/"
    c.request("GET", url, headers=h)
    r = c.getresponse()
    d = json.loads(r.read())
    c.close()
    return d.get("data", d) if isinstance(d, dict) else d

# 1. SteamDT: 今日/昨日统计 + 小时线
stdt_sum   = fetch("/index/statistics/v1/summary",  "api.steamdt.com")
stdt_daily = fetch("/index/transaction/trend/v1/all", "api.steamdt.com")

today_close = float(stdt_sum.get("broadMarketIndex", 0))
yest_ratio  = float(stdt_sum.get("diffYesterdayRatio", 0))
yest_close  = today_close / (1 + yest_ratio / 100.0) if yest_ratio else today_close

# SteamDT 今日成交数据
today_stats = stdt_sum.get("todayStatistics", {})
yest_stats  = stdt_sum.get("yesterdayStatistics", {})
today_tov   = float(today_stats.get("turnover", 0))
today_cnt   = int(today_stats.get("tradeNum", 0))
yest_tov    = float(yest_stats.get("turnover", 0))
yest_cnt    = int(yest_stats.get("tradeNum", 0))

# SteamDT 日期映射
stdt_turnover = {d[0]: float(d[1]) for d in stdt_daily}
stdt_count    = {d[0]: float(d[2]) for d in stdt_daily}

# SteamDT 小时线聚合日K（覆盖最近1-2天）
hist_hourly = stdt_sum.get("historyMarketIndexList", [])
daily_stdt  = defaultdict(list)
for item in hist_hourly:
    ts, price = int(item[0]), float(item[1])
    key = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    daily_stdt[key].append(price)

daily_stdt_ohlc = {}
for k, prices in daily_stdt.items():
    daily_stdt_ohlc[k] = {"open": prices[0], "high": max(prices), "low": min(prices), "close": prices[-1]}

print(f"SteamDT today={today_close} yest_close={yest_close:.2f}")
print(f"SteamDT 今日成交额={today_tov:,.2f} 成交数={today_cnt:,}")
print(f"SteamDT 小时聚合日K: {list(daily_stdt_ohlc.keys())}")

# 2. CSQAQ 日线 OHLC（价格）
csqaq = fetch("/api/v1/sub/kline?type=1day&id=1&maxTime=", "api.csqaq.com", "HXGPY1R7L5W7K7F3O4K1E2N8")
print(f"CSQAQ 日线: {len(csqaq)} 条")
if csqaq:
    first = csqaq[0]
    last  = csqaq[-1]
    dt_first = datetime.fromtimestamp(int(first["t"]) / 1000, tz=timezone.utc)
    dt_last  = datetime.fromtimestamp(int(last["t"])  / 1000, tz=timezone.utc)
    print(f"  {dt_first.strftime('%Y-%m-%d')} ~ {dt_last.strftime('%Y-%m-%d')}")

# 3. CSQAQ → SteamDT 比例因子
# 找两者的交集日期：CSQAQ 最后一天 ≈ SteamDT 的昨天
if csqaq:
    csq_last = csqaq[-1]
    csq_ts   = int(csq_last["t"]) / 1000
    csq_dt   = datetime.fromtimestamp(csq_ts, tz=timezone.utc)
    csq_date = csq_dt.strftime("%Y-%m-%d")
    csq_close = float(csq_last["c"])

    stdt_date = dt_last.strftime("%Y-%m-%d")  # same as csq_date
    stdt_close = float(daily_stdt_ohlc.get(csq_date, {}).get("close", yest_close))

    ratio = stdt_close / csq_close if csq_close else 1.0
    print(f"  交集日 {csq_date}: CSQAQ={csq_close} SteamDT={stdt_close} ratio={ratio:.4f}")
else:
    ratio = 1.0

# 4. 构建日K
dates  = []
values = []
ohlc   = []
volBar = []
volColor = []

for item in csqaq:
    ts     = int(item["t"])
    dt     = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    date_s = dt.strftime("%Y-%m-%d")

    # 价格：CSQAQ OHLC × 比例因子
    price  = float(item["c"]) * ratio
    op     = float(item["o"]) * ratio
    hp     = float(item["h"]) * ratio
    lp     = float(item["l"]) * ratio

    dates.append(date_s[5:])
    values.append(round(price, 2))

    # 成交量来源：SteamDT transaction trend
    stdt_tov = stdt_turnover.get(date_s, 0)
    stdt_cnt = int(stdt_count.get(date_s, 0))

    ohlc.append({
        "date":     date_s[5:],
        "open":     round(op, 2),
        "high":     round(hp, 2),
        "low":      round(lp, 2),
        "close":    round(price, 2),
        "volume":   stdt_cnt if stdt_cnt > 0 else 0,
        "turnover": round(stdt_tov, 2) if stdt_tov > 0 else 0,
    })

# 5. 如果 SteamDT 今天有小时数据但 CSQAQ 没有今天（后者日线要到晚上才更新）
# 补上今天的 SteamDT 小时聚合日K
today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
if today_key not in [d[5:] for d in dates] and today_key in daily_stdt_ohlc:
    dp  = daily_stdt_ohlc[today_key]
    dates.append(today_key[5:])
    values.append(round(dp["close"], 2))
    ohlc.append({
        "date":     today_key[5:],
        "open":     round(dp["open"], 2),
        "high":     round(dp["high"], 2),
        "low":      round(dp["low"], 2),
        "close":    round(dp["close"], 2),
        "volume":   today_cnt,
        "turnover": round(today_tov, 2),
    })

# volBar/volColor
max_vol = max((d.get("volume", 1) for d in ohlc), default=1) or 1
for i, o in enumerate(ohlc):
    volBar.append(max(20, round(o.get("volume", 0) / max_vol * 150)))
    prev = values[i-1] if i > 0 else values[0]
    volColor.append('#ef4444' if values[i] >= prev else '#22c55e')

# 6. 最新值
lt  = values[-1] if values else 0
pv  = values[-2] if len(values) > 1 else lt
chg = round((lt - pv) / pv * 100, 2) if pv else 0

print(f"\n数据验证:")
print(f"  最新指数: {lt} (涨跌: {chg}%)")
print(f"  日期范围: {dates[0]} ~ {dates[-1]} (共 {len(dates)} 天)")
print(f"  价格样本(最近5天): {values[-5:]}")
print(f"  成交量样本(最近5天): {[o['volume'] for o in ohlc[-5:]]}")
print(f"  成交额样本(最近5天): {[o['turnover'] for o in ohlc[-5:]]}")

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
    "todayStats":    {"turnover": round(today_tov, 2), "count": today_cnt},
    "yesterdayStats":{"turnover": round(yest_tov,  2), "count": yest_cnt},
    "surviveNum": int(stdt_sum.get("surviveNum") or 0),
    "holdersNum": int(stdt_sum.get("holdersNum") or 0),
}

with open(mjp, "w", encoding="utf-8") as f:
    json.dump(mj, f, ensure_ascii=False, indent=2)

print(f"\nmarket.json 写入: {len(ohlc)} 根日K")

# 8. Git push
repo = r"C:\Users\Lenovo\cs2-dashboard"
subprocess.run(["git", "-C", repo, "add", "."], check=True, capture_output=True)
r2 = subprocess.run(["git", "-C", repo, "commit", "-m",
    "feat: CSQAQ daily OHLC + SteamDT real turnover, full history restored"],
    capture_output=True)
msg = r2.stderr.strip() if r2.stderr else r2.stdout.strip()
print(f"Commit: {msg or 'OK'}")
r3 = subprocess.run(["git", "-C", repo, "push"], capture_output=True, text=True)
print(f"Push: {'OK' if r3.returncode == 0 else r3.stderr}")
