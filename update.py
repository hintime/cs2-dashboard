#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CS2 Dashboard 数据更新脚本
- ECOSteam API 获取持仓价格 → holdings.json
- CSQAQ API 获取异动数据 → market.json (alerts)
- 可选：SteamDT K-lines (需有效 API Key)
"""
import json, time, base64, urllib.request, urllib.error, subprocess, os, sys, ssl

# ═══════════════ CONFIG ═══════════════
PARTNER_ID = 'da740aa96cc14cc594371f95469c90ac'
CSQ_KEY = os.environ.get('CSQ_API_TOKEN', 'HXGPY1R7L5W7K7F3O4K1E2N8')
STEAM_KEY = os.environ.get('STEAMDT_KEY', '')
GH_TOKEN = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN', '')
REPO = 'hintime/cs2-dashboard'
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, '..') if SCRIPT_DIR.endswith('.github') else SCRIPT_DIR

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds

# SSL context (relaxed for CI)
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# ═══════════════ ECO SIGNING ═══════════════
_eco_key = None

def get_eco_key():
    global _eco_key
    if _eco_key is not None:
        return _eco_key
    from Crypto.PublicKey import RSA
    from Crypto.Signature import pkcs1_15
    from Crypto.Hash import SHA256
    key_b64 = os.environ.get('ECO_PRIVATE_KEY_B64')
    if not key_b64:
        key_path = os.path.join(DATA_DIR, 'eco_private_key.txt')
        if os.path.exists(key_path):
            with open(key_path, 'r') as f:
                key_b64 = f.read().strip()
        else:
            raise FileNotFoundError('ECO private key not found')
    pem = '-----BEGIN RSA PRIVATE KEY-----\n' + key_b64 + '\n-----END RSA PRIVATE KEY-----'
    _eco_key = RSA.import_key(pem)
    return _eco_key

def sign_eco(params):
    key = get_eco_key()
    from Crypto.Signature import pkcs1_15
    from Crypto.Hash import SHA256
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
    return base64.b64encode(pkcs1_15.new(key).sign(h)).decode()

# ═══════════════ HTTP HELPERS ═══════════════
def http_get(url, headers=None, timeout=15):
    req = urllib.request.Request(url, headers=headers or {})
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(RETRY_DELAY)

def http_post(url, body, headers=None, timeout=15):
    data = json.dumps(body, ensure_ascii=False).encode('utf-8') if isinstance(body, (dict, list)) else body
    hdrs = {'Content-Type': 'application/json'}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method='POST')
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(RETRY_DELAY)

def http_post_raw(url, body, headers=None, timeout=15):
    """Return raw bytes for GBK-encoded responses"""
    data = json.dumps(body, ensure_ascii=False).encode('utf-8') if isinstance(body, (dict, list)) else body
    hdrs = {'Content-Type': 'application/json'}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method='POST')
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                raw = r.read()
                for enc in ('utf-8', 'gbk', 'latin-1'):
                    try:
                        return json.loads(raw.decode(enc))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                return {}
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(RETRY_DELAY)

# ═══════════════ ECO PRICES ═══════════════
def fetch_eco_prices(hash_names):
    """Batch fetch ECO prices, returns {HashName: price_float}"""
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
        try:
            result = http_post(
                'https://openapi.ecosteam.cn/Api/Market/BatchSearchSellingPrice',
                params, timeout=30
            )
            if str(result.get('ResultCode')) == '0':
                for item in (result.get('ResultData') or []):
                    hn = item.get('HashName')
                    # Use MarketComprePrice (comprehensive) over MinPrice (can be artificially low)
                    raw = item.get('MarketComprePrice') or item.get('MinPrice') or item.get('Price') or '0'
                    try:
                        p = float(raw)
                    except (ValueError, TypeError):
                        p = 0.0
                    if hn and p > 0:
                        prices[hn] = p
            else:
                print(f'[WARN] ECO ResultCode={result.get("ResultCode")} batch {i//batch_size+1}', file=sys.stderr)
        except Exception as e:
            print(f'[ERROR] ECO batch {i//batch_size+1}: {e}', file=sys.stderr)
    return prices

# ═══════════════ CSQAQ ALERTS ═══════════════
def fetch_csqaq_alerts():
    """Fetch price change rankings from CSQAQ"""
    all_alerts = []
    seen_ids = set()

    for sort_key in ('price_up_1d', 'price_down_1d'):
        for page in range(1, 4):
            body = {
                'page_index': page,
                'page_size': 50,
                'filter': {'type': ['sticker', 'normal'], 'sort': [sort_key]},
                'show_recently_price': True
            }
            try:
                d = http_post_raw(
                    'https://api.csqaq.com/api/v1/info/get_rank_list',
                    body,
                    headers={'ApiToken': CSQ_KEY},
                    timeout=15
                )
                items = d.get('data', {})
                if isinstance(items, dict):
                    items = items.get('data', [])
                if not items:
                    break
                for item in items:
                    item_id = item.get('id')
                    if item_id in seen_ids:
                        continue
                    seen_ids.add(item_id)
                    all_alerts.append({
                        'id': item_id,
                        'name_cn': item.get('name', ''),
                        'exterior': item.get('exterior_localized_name', ''),
                        'rarity': item.get('rarity_localized_name', ''),
                        'price': float(item.get('buff_sell_price') or 0),
                        'rate_1': round(float(item.get('buff_price_chg') or item.get('sell_price_rate_1') or 0), 2),
                        'rate_7': round(float(item.get('sell_price_rate_7') or 0), 2),
                        'rate_30': round(float(item.get('sell_price_rate_30') or 0), 2),
                        'rank_num': item.get('rank_num', 0),
                        'img': item.get('img', ''),
                    })
                if len(items) < 50:
                    break
            except Exception as e:
                print(f'[WARN] CSQAQ {sort_key} page {page}: {e}', file=sys.stderr)
            time.sleep(0.5)

    # Sort by absolute change, dedup
    all_alerts.sort(key=lambda x: abs(x.get('rate_1', 0)), reverse=True)
    return all_alerts

# ═══════════════ STEAMDT K-LINES (optional) ═══════════════
def fetch_steamdt_klines(items_list):
    """Fetch K-line data from SteamDT if API key is valid"""
    if not STEAM_KEY or STEAM_KEY == 'test_key':
        print('[INFO] SteamDT key not configured, skipping K-lines')
        return {}

    # Verify key works first
    try:
        test = http_get(
            'https://open.steamdt.com/open/cs2/v1/price/single?marketHashName=AK-47%20%7C%20Redline%20(Field-Tested)',
            headers={'Authorization': f'Bearer {STEAM_KEY}'}
        )
        if not test.get('success'):
            print(f'[WARN] SteamDT key invalid (code={test.get("errorCode")}), skipping K-lines')
            return {}
    except Exception as e:
        print(f'[WARN] SteamDT unreachable: {e}, skipping K-lines')
        return {}

    kline_data = {}
    for item in items_list:
        name = item.get('name_en') or item.get('name', '')
        try:
            resp = http_post(
                'https://open.steamdt.com/open/cs2/item/v1/kline',
                {'marketHashName': name, 'type': 2, 'platform': 'BUFF'},
                headers={'Authorization': f'Bearer {STEAM_KEY}'},
                timeout=20
            )
            if resp.get('success') and resp.get('data'):
                raw = resp['data']
                # Normalize: data can be object with numeric keys or array
                if isinstance(raw, dict):
                    keys = sorted(raw.keys(), key=lambda x: int(x) if x.isdigit() else x)
                    raw = [raw[k] for k in keys]
                parsed = []
                for p in raw:
                    if isinstance(p, (list, tuple)) and len(p) >= 5:
                        # SteamDT: [ts, open, close, high, low] → [ts, open, high, low, close, vol]
                        parsed.append([int(p[0]), float(p[1]), float(p[3]), float(p[4]), float(p[2]), 0])
                if parsed:
                    kline_data[name] = parsed
                    print(f'  K-line OK: {name[:35]} → {len(parsed)} pts')
        except Exception as e:
            print(f'  K-line ERR: {name[:35]}: {e}', file=sys.stderr)
        time.sleep(0.3)  # rate limit

    return kline_data

# ═══════════════ GITHUB PUSH ═══════════════
def github_push_file(path, content_str, message):
    """Push a file to GitHub via Contents API"""
    if not GH_TOKEN:
        print('[INFO] No GitHub token, skipping push')
        return False
    api_url = f'https://api.github.com/repos/{REPO}/contents/{path}'
    headers = {
        'Authorization': f'token {GH_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
    }
    # Get current SHA
    sha = None
    try:
        req = urllib.request.Request(f'{api_url}?ref=main', headers=headers)
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            sha = json.loads(r.read().decode())['sha']
    except Exception:
        pass  # File might not exist yet

    b64 = base64.b64encode(content_str.encode('utf-8')).decode('ascii')
    body = json.dumps({'message': message, 'content': b64, 'branch': 'main'})
    if sha:
        body_data = json.loads(body)
        body_data['sha'] = sha
        body = json.dumps(body_data)

    req = urllib.request.Request(api_url, data=body.encode('utf-8'), headers=headers, method='PUT')
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            result = json.loads(r.read().decode())
            print(f'[OK] Pushed {path}: {result["commit"]["sha"][:8]}')
            return True
    except urllib.error.HTTPError as e:
        print(f'[ERROR] Push {path} failed: HTTP {e.code}: {e.read().decode()[:200]}', file=sys.stderr)
        return False

def git_push_locally(files, message):
    """Push via local git (for local cron or CI with checkout)"""
    for f in files:
        subprocess.run(['git', 'add', f], check=True, cwd=DATA_DIR)
    subprocess.run(['git', 'commit', '-m', message], check=True, cwd=DATA_DIR)
    subprocess.run(['git', 'push'], check=True, cwd=DATA_DIR)
    print(f'[OK] Git pushed: {message}')

# ═══════════════ MAIN ═══════════════
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
    # mode: 'all', 'prices', 'alerts', 'klines'

    print(f'=== CS2 Dashboard Update ({mode}) ===')

    # ── Update ECO prices → holdings.json ──
    if mode in ('all', 'prices'):
        holdings_path = os.path.join(DATA_DIR, 'holdings.json')
        with open(holdings_path, 'r', encoding='utf-8') as f:
            holdings = json.load(f)

        items = holdings.get('items', [])
        hash_names = [it['market_hash'] for it in items if it.get('market_hash')]
        print(f'[ECO] Fetching prices for {len(hash_names)} items...')

        prices = fetch_eco_prices(hash_names)
        print(f'[ECO] Got {len(prices)} prices')

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

        with open(holdings_path, 'w', encoding='utf-8') as f:
            json.dump(holdings, f, ensure_ascii=False, indent=2)

        pnl = total_market - total_cost
        pnl_pct = pnl / total_cost * 100 if total_cost else 0
        print(f'[ECO] Updated {updated}/{len(hash_names)} | Cost={total_cost:.0f} Market={total_market:.0f} PnL={pnl:+.0f} ({pnl_pct:+.1f}%)')

        if os.environ.get('GITHUB_ACTIONS'):
            # CI: use GitHub API push
            github_push_file(
                'holdings.json',
                json.dumps(holdings, ensure_ascii=False, indent=2),
                f'chore: update ECO prices {time.strftime("%m-%d %H:%M")}'
            )
        else:
            # Local: use git push
            git_push_locally(['holdings.json'], f'chore: update ECO prices {time.strftime("%Y-%m-%d %H:%M")}')

    # ── Update CSQAQ alerts → market.json ──
    if mode in ('all', 'alerts'):
        print('[CSQAQ] Fetching alerts...')
        try:
            alerts = fetch_csqaq_alerts()
            print(f'[CSQAQ] Got {len(alerts)} alerts')

            market_path = os.path.join(DATA_DIR, 'market.json')
            with open(market_path, 'r', encoding='utf-8') as f:
                market = json.load(f)
            market['alerts'] = alerts
            market['alerts_updated'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

            with open(market_path, 'w', encoding='utf-8') as f:
                json.dump(market, f, ensure_ascii=False, indent=2)

            if os.environ.get('GITHUB_ACTIONS'):
                github_push_file(
                    'market.json',
                    json.dumps(market, ensure_ascii=False, indent=2),
                    f'chore: update alerts {time.strftime("%m-%d %H:%M")}'
                )
            else:
                git_push_locally(['market.json'], f'chore: update alerts {time.strftime("%Y-%m-%d %H:%M")}')
        except Exception as e:
            print(f'[CSQAQ] Failed: {e}', file=sys.stderr)

    # ── Update SteamDT K-lines (optional) ──
    if mode in ('all', 'klines') and STEAM_KEY:
        print('[SteamDT] Fetching K-lines...')
        try:
            market_path = os.path.join(DATA_DIR, 'market.json')
            with open(market_path, 'r', encoding='utf-8') as f:
                market = json.load(f)
            items_list = market.get('items', [])
            kline_data = fetch_steamdt_klines(items_list)
            if kline_data:
                for item in items_list:
                    name = item.get('name_en') or item.get('name', '')
                    if name in kline_data:
                        item['kline'] = kline_data[name]
                market['items'] = items_list
                with open(market_path, 'w', encoding='utf-8') as f:
                    json.dump(market, f, ensure_ascii=False, indent=2)
                if os.environ.get('GITHUB_ACTIONS'):
                    github_push_file(
                        'market.json',
                        json.dumps(market, ensure_ascii=False, indent=2),
                        f'chore: update K-lines {time.strftime("%m-%d %H:%M")}'
                    )
                else:
                    git_push_locally(['market.json'], f'chore: update K-lines {time.strftime("%Y-%m-%d %H:%M")}')
        except Exception as e:
            print(f'[SteamDT] K-lines failed: {e}', file=sys.stderr)

    print('=== Done ===')

if __name__ == '__main__':
    main()
