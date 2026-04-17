#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Debug: test ECO API with full holdings list"""
import json, time, base64, urllib.request
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256

PK_B64 = 'MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC7kHLBiD8GVy75IwzB52UmxPyjiKKGiRyO4aa2J5kbQO96ssA6YWDIZG88cGfRi5MVtD62eDgVeaw390eIgEwXvGue050nzAue/R+8jjyfQlUmYskdBfkhTJRTCpgGzzk/by5oFbFOA4Twz5iXgFl7cW3oE07w1diAHmrO4rixQ5sdX1R/LwLZreiIyoHYNClvl0iILQx4DwDpzxCBYHmneSQwxEJGdxsgz9xYoK8QUoKliGf9dDanY1fGXtxscy8uWA23aWohimBdh/uDHzyCSs1xRUBUgYflDz4RNI5fTNd2cGp7aKDaGnhbsdLsPGSLcGoYPjyys6vqDCM2/qLFAgMBAAECggEACj0JPUNmw1MXgJMso1oHpWfhLZEWuWwlx66NdzSD+57zY5nQe0StBTX8SiA4U+cqonzqDnOosL1pTKMeKmyXGsBBif7dqC+PySrijwb0TAeRgSypHevhTJ4dm5yAriB6LMUGKLmEafCFvXprhzDtptrLJ9JZVQqrTIUR31S0xbzwf8mVwhqgi/hHc1R1DXTOBQiQyx1gB/t896hFciEhuOXcov31kbKE4aFoYF/TWw7IWeyEF/ncVrRINL9U4hZxz4lluLa45MCR+8uN6Av8QTbvhADarF3flC/HGX9NSm7xTtkwypGgqt7Qm6uUnOwYuOn8ROnlV6duw229I1l2KQKBgQDc5/9gd9+nSIZ0X8eUOIQQZEVal6VvN3vWKsFqHLswJ6JSSGjliSQsNxr+utvzMR8djMmLrfMd13BLVGlLmOvfXYV1JVTFuRZs/12Xq51U8BrMywzqWyJBfTDIcfwW43H+oscSLMG2rrqC+NcgUP/8k9lW35QX7mrULTX6XGttSQKBgQDZXHhq412A/Ge8/RMAeV8qSKuyLI55POl40d5S0vlF/aXGZyR3I9POpYNSYc38BBFwss5N6yshfYJ0kZ8yA9mQu+HltdjGSyPH1UxibV+wcY93CzNYBAHmKMBanLqeqHMrR2Xjv0mNwXqtAp3Nvs3fD2YXUD5nU26+4WXJphi1nQKBgQDR68zsmT15tBvBHvuDSKmHAiI90nmtVGZjwMGH2sGvIxrHYnP8G/S556vJgTxev8E3zYABMk4jf4UAsLhW1HzhB/g4uD70ncxHy+veo4ChJIHzNsmRMwU8goEHGfparcy4E2tlRA7ZUPWAXIPh+9cm6EDSoygSDciK1GPFBGo5sQKBgQCt36uwDWr5yG8Pnf46TdzTjUhTghMCZrh43qES7hNbarjWiiGAcJd5Yas4FmbZJ0PwPAiOCgX5h1X4+5g2QSAkCDd/MsVScj8QFs9AmS+HjH/wAXSz/piqTYT5txAN5MAkKbwWwCkNjW0dws8LC4vR2JaZJaaVrwcTCGkNMqHnfQKBgDTzmtc6V4kCvnH52ZT4vgS/sMmV35R0nx8rKKw6PGQVNQyRfN6HNKZ+e3uioCodY2bDXUlrD99E5XFaPtLrHW3ws+mAIqxwy3QaOX+aR8sbgne9wTVGc5WQXvyT3fbJ6tuAeUjCq1XCHI4/jSvRwEyn/EFPCZJKyR9xE+okl3s7'
PRIVATE_KEY = RSA.import_key('-----BEGIN RSA PRIVATE KEY-----\n' + PK_B64 + '\n-----END RSA PRIVATE KEY-----')

def sign_eco(params):
    sorted_params = sorted(params.items(), key=lambda x: x[0].lower())
    parts = []
    for k, v in sorted_params:
        if v is None or v == '':
            continue
        if isinstance(v, (list, dict)):
            v = json.dumps(v, separators=(',', ':'), ensure_ascii=False)
        parts.append(f'{k}={v}')
    sign_str = '&'.join(parts)
    h = SHA256.new(sign_str.encode('utf-8'))
    return base64.b64encode(pkcs1_15.new(PRIVATE_KEY).sign(h)).decode()

# Load holdings
with open('holdings.json', 'r', encoding='utf-8') as f:
    holdings = json.load(f)

items = holdings['items']
hash_names = [it['market_hash'] for it in items if it.get('market_hash')]
print(f'Total items: {len(hash_names)}')

# Fetch all in one batch (32 < 100)
params = {
    'PartnerId': 'da740aa96cc14cc594371f95469c90ac',
    'Timestamp': str(int(time.time())),
    'GameID': '730',
    'HashName': hash_names
}
params['Sign'] = sign_eco(params)

url = 'https://openapi.ecosteam.cn/Api/Market/BatchSearchSellingPrice'
data = json.dumps(params, ensure_ascii=False).encode('utf-8')
req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
resp = urllib.request.urlopen(req, timeout=30)
result = json.loads(resp.read().decode('utf-8'))

rc = result.get('ResultCode')
rd = result.get('ResultData') or []
print(f'ResultCode: {rc}, ResultData count: {len(rd)}')

prices = {}
for item in rd:
    hn = item.get('HashName')
    raw = item.get('MinPrice') or item.get('Price') or '0'
    try:
        p = float(raw)
    except:
        p = 0.0
    if hn:
        prices[hn] = p

print(f'Parsed prices: {len(prices)}')
for hn, p in sorted(prices.items(), key=lambda x: -x[1])[:10]:
    print(f'  {hn}: {p}')

# Now update holdings
updated = 0
for item in items:
    hn = item.get('market_hash')
    if hn and hn in prices:
        item['price'] = prices[hn]
        updated += 1

total_cost = sum(it.get('cost', 0) * it.get('qty', 1) for it in items)
total_market = sum(it.get('price', 0) * it.get('qty', 1) for it in items)
holdings['total_cost'] = round(total_cost, 2)
holdings['total_market'] = round(total_market, 2)
holdings['update_time'] = time.strftime('%Y-%m-%d %H:%M:%S')

with open('holdings.json', 'w', encoding='utf-8') as f:
    json.dump(holdings, f, ensure_ascii=False, indent=2)

pnl = total_market - total_cost
pnl_pct = pnl / total_cost * 100 if total_cost else 0
print(f'\nUpdated {updated}/{len(hash_names)} items')
print(f'Cost: {total_cost:.2f} | Market: {total_market:.2f} | PnL: {pnl:+.2f} ({pnl_pct:+.2f}%)')
