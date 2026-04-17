#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用 ECOSteam API 更新持仓价格，并推送到 GitHub
"""
import json, time, base64, urllib.request, subprocess, os, sys

from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256

PARTNER_ID = 'da740aa96cc14cc594371f95469c90ac'
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 从环境变量或本地文件加载私钥（优先环境变量 ECO_PRIVATE_KEY_B64）
def load_private_key():
    key_b64 = os.environ.get('ECO_PRIVATE_KEY_B64')
    if not key_b64:
        key_path = os.path.join(SCRIPT_DIR, 'eco_private_key.txt')
        if os.path.exists(key_path):
            with open(key_path, 'r') as f:
                key_b64 = f.read().strip()
        else:
            raise FileNotFoundError('ECO private key not found. Set ECO_PRIVATE_KEY_B64 env var or create eco_private_key.txt')
    pem = '-----BEGIN RSA PRIVATE KEY-----\n' + key_b64 + '\n-----END RSA PRIVATE KEY-----'
    return RSA.import_key(pem)

PRIVATE_KEY = load_private_key()

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

def fetch_prices(hash_names):
    """批量获取价格，返回 {HashName: float_price}"""
    prices = {}
    batch_size = 100
    for i in range(0, len(hash_names), batch_size):
        batch = hash_names[i:i+batch_size]
        params = {
            'PartnerId': PARTNER_ID,
            'Timestamp': str(int(time.time())),
            'GameID': '730',
            'HashName': batch
        }
        params['Sign'] = sign_eco(params)
        url = 'https://openapi.ecosteam.cn/Api/Market/BatchSearchSellingPrice'
        data = json.dumps(params, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read().decode('utf-8'))
            if result.get('ResultCode') == 0:
                for item in (result.get('ResultData') or []):
                    hn = item.get('HashName')
                    raw = item.get('MinPrice') or item.get('Price') or '0'
                    try:
                        p = float(raw)
                    except (ValueError, TypeError):
                        p = 0.0
                    if hn and p > 0:
                        prices[hn] = p
            else:
                print(f'[WARN] ECO ResultCode={result.get("ResultCode")} batch {i//batch_size+1}', file=sys.stderr)
        except Exception as e:
            print(f'[ERROR] batch {i//batch_size+1}: {e}', file=sys.stderr)
    return prices

def main():
    holdings_path = os.path.join(SCRIPT_DIR, 'holdings.json')

    with open(holdings_path, 'r', encoding='utf-8') as f:
        holdings = json.load(f)

    items = holdings.get('items', [])
    hash_names = [it['market_hash'] for it in items if it.get('market_hash')]
    sys.stdout.buffer.write(f'Fetching prices for {len(hash_names)} items...\n'.encode('utf-8'))

    prices = fetch_prices(hash_names)
    sys.stdout.buffer.write(f'Got prices for {len(prices)} items\n'.encode('utf-8'))

    updated = 0
    for item in items:
        hn = item.get('market_hash')
        if hn and hn in prices:
            item['price'] = prices[hn]
            updated += 1

    total_cost   = sum(it.get('cost', 0)  * it.get('qty', 1) for it in items)
    total_market = sum(it.get('price', 0) * it.get('qty', 1) for it in items)
    holdings['total_cost']   = round(total_cost, 2)
    holdings['total_market'] = round(total_market, 2)
    holdings['update_time']  = time.strftime('%Y-%m-%d %H:%M:%S')

    with open(holdings_path, 'w', encoding='utf-8') as f:
        json.dump(holdings, f, ensure_ascii=False, indent=2)

    pnl = total_market - total_cost
    pnl_pct = pnl / total_cost * 100 if total_cost else 0
    msg = f'Updated {updated}/{len(hash_names)} | Cost: {total_cost:.2f} | Market: {total_market:.2f} | PnL: {pnl:+.2f} ({pnl_pct:+.2f}%)\n'
    sys.stdout.buffer.write(msg.encode('utf-8'))

    # git push
    os.chdir(SCRIPT_DIR)
    subprocess.run(['git', 'add', 'holdings.json'], check=True)
    subprocess.run(['git', 'commit', '-m', f'chore: update holdings via ECO {time.strftime("%Y-%m-%d %H:%M")}'], check=True)
    subprocess.run(['git', 'push'], check=True)
    sys.stdout.buffer.write(b'Pushed to GitHub.\n')

if __name__ == '__main__':
    main()
