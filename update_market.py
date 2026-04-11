import http.client, ssl, json, subprocess
from datetime import datetime, timezone
from collections import defaultdict

ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

conn = http.client.HTTPSConnection("api.steamdt.com", context=ctx, timeout=15)

conn.request("GET", "/index/statistics/v1/summary", headers={
    "User-Agent": "Mozilla/5.0", "Referer": "https://steamdt.com/"
})
summary = json.loads(conn.getresponse().read()).get("data", {})

conn.request("GET", "/index/transaction/trend/v1/all", headers={
    "User-Agent": "Mozilla/5.0", "Referer": "https://steamdt.com/"
})
daily_raw = json.loads(conn.getresponse().read()).get("data", [])
conn.close()

# 1. 今日收盘价 = broadMarketIndex
today_close = float(summary.get("broadMarketIndex", 0))
print(f"今日收盘指数: {today_close}")

# 2. 今日成交数据
today_stats = summary.get("todayStatistics", {})
yest_stats  = summary.get("yesterdayStatistics", {})
print(f"今日成交额: {float(today_stats.get('turnover') or 0):,.2f}")
print(f"昨日成交额: {float(yest_stats.get('turnover') or 0):,.2f}")

# 3. 反向递推：用 diffYesterdayRatio 计算历史日收盘价
# daily_raw 是升序(最老→最新)，格式: [date, turnover, count, diffYesterdayRatio]
# 反向遍历，从今日向前推
dates_rev  = []
prices_rev = []   # 日收盘价
ohlc_rev   = []
volBar_rev = []
volColor_rev = []
max_vol = max(float(d[2]) for d in daily_raw) if daily_raw else 1

# 锚点：今日收盘价
current_close = today_close
current_date  = daily_raw[-1][0] if daily_raw else datetime.now().strftime("%Y-%m-%d")

# 今日已有统计
today_count    = float(today_stats.get("tradeNum") or 0)
today_turnover = float(today_stats.get("turnover") or 0)

# 反向推算日线价格
for i in range(len(daily_raw) - 1, -1, -1):
    item   = daily_raw[i]
    date_s = item[0]
    turnover = float(item[1])
    count    = float(item[2])
    # diffYesterdayRatio: 前一天的涨跌比例 (e.g. -0.0149 = -1.49%)
    ratio    = float(item[3]) if len(item) > 3 else 0.0

    # 反向：当前收盘 = 下一日收盘 / (1 + ratio)
    if i == len(daily_raw) - 1:
        # 今日：用今日成交数据
        index_val = current_close
    else:
        # 历史日：用 ratio 反推
        index_val = current_close / (1 + ratio / 100.0) if ratio != 0 else current_close

    dates_rev.append(date_s[5:])
    prices_rev.append(round(index_val, 2))
    volBar_rev.append(max(20, round(count / max_vol * 150)))
    volColor_rev.append('#ef4444' if ratio >= 0 else '#22c55e')

    # 更新锚点
    current_close = index_val

# 反转回升序
dates    = list(reversed(dates_rev))
prices   = list(reversed(prices_rev))
volBar   = list(reversed(volBar_rev))
volColor = list(reversed(volColor_rev))

# 4. OHLC: 最近几天用小时数据，历史用 (close=close, open=close, high=close, low=close)
hist_hourly = summary.get("historyMarketIndexList", [])
daily_h = defaultdict(list)
for item in hist_hourly:
    ts, price = int(item[0]), float(item[1])
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    daily_h[dt.strftime("%Y-%m-%d")].append(price)

# 从 reversed list 重建 ohlc（同样反转顺序）
ohlc_rev2 = []
for i in range(len(dates_rev) - 1, -1, -1):
    date_s = "2026-" + dates_rev[i]
    item   = daily_raw[i]
    turnover = float(item[1])
    count    = float(item[2])
    ratio    = float(item[3]) if len(item) > 3 else 0.0

    h_prices = daily_h.get(date_s, [])
    if h_prices:
        op = round(h_prices[0], 2)
        hp = round(max(h_prices), 2)
        lp = round(min(h_prices), 2)
        cp = round(prices_rev[i], 2)
    else:
        cp = round(prices_rev[i], 2)
        op = hp = lp = cp

    ohlc_rev2.append({
        "date":    dates_rev[i],
        "open":    op,
        "high":    hp,
        "low":     lp,
        "close":   cp,
        "volume":  int(count),
        "turnover": round(turnover, 2),
    })

ohlc = list(reversed(ohlc_rev2))

# 5. 最新值
lt  = prices[-1] if prices else 0
pv  = prices[-2] if len(prices) > 1 else lt
chg = round((lt - pv) / pv * 100, 2) if pv else 0

print(f"\n数据验证:")
print(f"  最新: {lt} (涨跌: {chg}%)")
print(f"  历史价格样本 (最近5天): {prices[-5:]}")
print(f"  历史价格样本 (最老5天): {prices[:5]}")
print(f"  最新日K: {ohlc[-1] if ohlc else None}")

# 6. 写入 market.json
mjp = r"C:\Users\Lenovo\cs2-dashboard\market.json"
with open(mjp, "r", encoding="utf-8") as f:
    mj = json.load(f)

mj["index"] = {
    "latest":   round(lt, 2),
    "change":   chg,
    "dates":    dates,
    "values":   prices,   # 日收盘价（用于 line chart）
    "min":      round(min(prices), 2),
    "max":      round(max(prices), 2),
    "ohlc":     ohlc,
    "volBar":   volBar,
    "volColor": volColor,
    "todayStats": {
        "turnover": round(today_turnover, 2),
        "count":    int(today_count),
    },
    "yesterdayStats": {
        "turnover": round(float(yest_stats.get("turnover") or 0), 2),
        "count":    int(yest_stats.get("tradeNum") or 0),
    },
    "surviveNum": int(summary.get("surviveNum") or 0),
    "holdersNum": int(summary.get("holdersNum") or 0),
    "perfScore": 0,
}

with open(mjp, "w", encoding="utf-8") as f:
    json.dump(mj, f, ensure_ascii=False, indent=2)

print(f"\nmarket.json 写入: {len(ohlc)} 根日K")

# 7. Git push
repo = r"C:\Users\Lenovo\cs2-dashboard"
subprocess.run(["git", "-C", repo, "add", "."], check=True, capture_output=True)
r2 = subprocess.run(["git", "-C", repo, "commit", "-m",
    "fix: use diffYesterdayRatio back-calculation for historical index prices"],
    capture_output=True)
print(f"Commit: {'OK' if r2.returncode == 0 else r2.stderr}")
r3 = subprocess.run(["git", "-C", repo, "push"], capture_output=True)
print(f"Push: {'OK' if r3.returncode == 0 else r3.stderr}")
