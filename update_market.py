import http.client, ssl, json, subprocess
from datetime import datetime, timezone

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

print(f"SteamDT today={today_close} yest_close={yest_close:.2f}")
print(f"SteamDT 今日成交额={today_tov:,.2f} 成交数={today_cnt:,}")

# 2. CSQAQ 日线 OHLC（价格）- 返回 dict 格式
csqaq = fetch("/api/v1/sub/kline?type=1day&id=1&maxTime=", "api.csqaq.com", "HXGPY1R7L5W7K7F3O4K1E2N8")
print(f"CSQAQ 日线: {len(csqaq)} 条")

if not csqaq:
    print("ERROR: CSQAQ no data!")
    exit(1)

# 3. CSQAQ → SteamDT 比例因子（用最后一个有效数据点）
csq_last = csqaq[-1]
csq_ts   = int(csq_last["t"]) / 1000
csq_dt   = datetime.fromtimestamp(csq_ts, tz=timezone.utc)
csq_date = csq_dt.strftime("%Y-%m-%d")
csq_close = float(csq_last["c"])

# 找 SteamDT 小时线中的同一天数据
daily_stdt = {}
for item in hist_hourly:
    ts, price = int(item[0]), float(item[1])
    key = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    if key not in daily_stdt:
        daily_stdt[key] = []
    daily_stdt[key].append(price)

stdt_close = 0
if csq_date in daily_stdt and daily_stdt[csq_date]:
    stdt_close = daily_stdt[csq_date][-1]  # last hourly close
else:
    stdt_close = yest_close  # fallback

ratio = stdt_close / csq_close if csq_close else 1.0
print(f"  交集日 {csq_date}: CSQAQ={csq_close} SteamDT={stdt_close} ratio={ratio:.4f}")

# 4. 构建日K - 使用完整日期 YYYY-MM-DD 作为唯一键
ohlc_by_date = {}  # key: "YYYY-MM-DD", value: OHLC data

for item in csqaq:
    ts     = int(item["t"])
    dt     = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    date_s = dt.strftime("%Y-%m-%d")  # 完整日期
    date_short = dt.strftime("%m-%d")  # 显示用

    price  = float(item["c"]) * ratio
    op     = float(item["o"]) * ratio
    hp     = float(item["h"]) * ratio
    lp     = float(item["l"]) * ratio

    stdt_tov = stdt_turnover.get(date_s, 0)
    stdt_cnt = int(stdt_count.get(date_s, 0))

    ohlc_by_date[date_s] = {
        "date":     date_short,
        "dateFull": date_s,
        "open":     round(op, 2),
        "high":     round(hp, 2),
        "low":      round(lp, 2),
        "close":    round(price, 2),
        "volume":   stdt_cnt,
        "turnover": round(stdt_tov, 2),
    }

# 5. 补上今天的 SteamDT 小时聚合日K（如果今天不在 CSQAQ 里）
today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
if today_key not in ohlc_by_date and today_key in daily_stdt:
    prices = daily_stdt[today_key]
    ohlc_by_date[today_key] = {
        "date":     today_key[5:],  # MM-DD
        "dateFull": today_key,
        "open":     round(prices[0], 2),
        "high":     round(max(prices), 2),
        "low":      round(min(prices), 2),
        "close":    round(prices[-1], 2),
        "volume":   today_cnt,
        "turnover": round(today_tov, 2),
    }
    print(f"补充今日 {today_key} SteamDT 小时聚合")

# 6. 按日期排序输出
sorted_dates = sorted(ohlc_by_date.keys())
dates  = [ohlc_by_date[d]["date"] for d in sorted_dates]
values = [ohlc_by_date[d]["close"] for d in sorted_dates]
ohlc   = [ohlc_by_date[d] for d in sorted_dates]

# volBar/volColor
max_vol = max((d.get("volume", 1) for d in ohlc), default=1) or 1
volBar = []
volColor = []
for i, o in enumerate(ohlc):
    volBar.append(max(20, round(o.get("volume", 0) / max_vol * 150)))
    prev = values[i-1] if i > 0 else values[0]
    volColor.append('#ef4444' if values[i] >= prev else '#22c55e')

# 7. 最新值
lt  = values[-1] if values else 0
pv  = values[-2] if len(values) > 1 else lt
chg = round((lt - pv) / pv * 100, 2) if pv else 0

print(f"\n数据验证:")
print(f"  最新指数: {lt} (涨跌: {chg}%)")
print(f"  日期范围: {sorted_dates[0]} ~ {sorted_dates[-1]} (共 {len(sorted_dates)} 天)")
print(f"  唯一日期数: {len(set(dates))}")
print(f"  价格样本(最近5天): {values[-5:]}")
print(f"  成交量样本(最近5天): {[o['volume'] for o in ohlc[-5:]]}")

# 8. 写入 market.json
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

# 8.5 更新时间
now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
mj["update_time"] = now_str

# 9. Git push
repo = r"C:\Users\Lenovo\cs2-dashboard"
subprocess.run(["git", "-C", repo, "add", "."], check=True, capture_output=True)
r2 = subprocess.run(["git", "-C", repo, "commit", "-m",
    "fix: use full YYYY-MM-DD dates to avoid year collision"],
    capture_output=True)
msg = r2.stderr.strip() if r2.stderr else r2.stdout.strip()
print(f"Commit: {msg or 'OK'}")
r3 = subprocess.run(["git", "-C", repo, "push"], capture_output=True, text=True)
print(f"Push: {'OK' if r3.returncode == 0 else r3.stderr}")
