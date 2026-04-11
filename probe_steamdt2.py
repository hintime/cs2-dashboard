import http.client, ssl, json

ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

conn = http.client.HTTPSConnection("api.steamdt.com", context=ctx, timeout=15)

conn.request("GET", "/index/transaction/trend/v1/all", headers={
    "User-Agent": "Mozilla/5.0", "Referer": "https://steamdt.com/"
})
data = json.loads(conn.getresponse().read())
daily = data.get("data", [])
print(f"日线总数: {len(daily)}")
print(f"每条长度: {[len(d) for d in daily[:5]]}")
print(f"每条完整内容: {daily[-5:]}")

# 探 summary 的完整结构
conn.request("GET", "/index/statistics/v1/summary", headers={
    "User-Agent": "Mozilla/5.0", "Referer": "https://steamdt.com/"
})
sum_data = json.loads(conn.getresponse().read()).get("data", {})
print(f"\nsummary keys: {list(sum_data.keys())}")
print(f"historyMarketIndexList len: {len(sum_data.get('historyMarketIndexList', []))}")
print(f"historyMarketIndexList: {sum_data.get('historyMarketIndexList', [])}")

# 探 /index/trend/v1/summary
conn.request("GET", "/index/trend/v1/summary", headers={
    "User-Agent": "Mozilla/5.0", "Referer": "https://steamdt.com/"
})
r = conn.getresponse()
raw = r.read()
try:
    trend_data = json.loads(raw)
    print(f"\n/index/trend/v1/summary: {r.status}, success={trend_data.get('success')}")
    if trend_data.get("success"):
        dd = trend_data.get("data", {})
        print(f"  keys: {list(dd.keys())}")
        print(f"  data: {str(dd)[:500]}")
except:
    print(f"\n/index/trend/v1/summary: {r.status} non-JSON: {raw[:200]}")

conn.close()
