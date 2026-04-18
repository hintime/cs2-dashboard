#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CS2 Dashboard 数据更新脚本 (优化版)
- ECOSteam API 获取持仓价格 → holdings.json
- CSQAQ API 获取异动数据 → market.json (alerts)
- 可选：SteamDT K-lines (需有效 API Key)

优化：
- 并发请求（concurrent.futures）
- 数据缓存复用（alerts + recommendations 共享）
- 批量处理
"""
import json, time, base64, urllib.request, urllib.error, subprocess, os, sys, ssl
from concurrent.futures import ThreadPoolExecutor, as_completed

# ═══════════════ CONFIG ═══════════════
PARTNER_ID = 'da740aa96cc14cc594371f95469c90ac'
CSQ_KEY = os.environ.get('CSQ_API_TOKEN', 'HXGPY1R7L5W7K7F3O4K1E2N8')
STEAM_KEY = os.environ.get('STEAMDT_KEY', '')
GH_TOKEN = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN', '')
REPO = 'hintime/cs2-dashboard'
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, '..') if SCRIPT_DIR.endswith('.github') else SCRIPT_DIR

MAX_RETRIES = 3
RETRY_DELAY = 2

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# Track which files were modified
dirty_files = set()

# ═══════════════ ECO SIGNING ═══════════════
_eco_key = None

def get_eco_key():
    global _eco_key
    if _eco_key is not None:
        return _eco_key
    from Crypto.PublicKey import RSA
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
    from Crypto.Signature import pkcs1_15
    from Crypto.Hash import SHA256
    key = get_eco_key()
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
    """Return parsed JSON, auto-detecting encoding (UTF-8/GBK/Latin-1)"""
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

# ═══════════════ ECO PRICES (并发) ═══════════════
def fetch_eco_prices(hash_names):
    """Batch fetch ECO prices → {HashName: price_float} (并发)"""
    prices = {}
    batch_size = 100
    batches = [hash_names[i:i+batch_size] for i in range(0, len(hash_names), batch_size)]
    
    def fetch_batch(batch, idx):
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
            batch_prices = {}
            if str(result.get('ResultCode')) == '0':
                for item in (result.get('ResultData') or []):
                    hn = item.get('HashName')
                    raw = item.get('MarketComprePrice') or item.get('MinPrice') or item.get('Price') or '0'
                    try:
                        p = float(raw)
                    except (ValueError, TypeError):
                        p = 0.0
                    if hn and p > 0:
                        batch_prices[hn] = p
            return batch_prices
        except Exception as e:
            print(f'[ERROR] ECO batch {idx}: {e}', file=sys.stderr)
            return {}
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_batch, batch, i): i for i, batch in enumerate(batches)}
        for future in as_completed(futures):
            prices.update(future.result())
    
    return prices

# ═══════════════ CSQAQ ALERTS (并发) ═══════════════
_cached_alerts = None  # 全局缓存，供 recommendations 复用

def fetch_csqaq_alerts(use_cache=True):
    """Fetch price change rankings from CSQAQ (并发，带缓存)"""
    global _cached_alerts
    
    if use_cache and _cached_alerts is not None:
        return _cached_alerts
    
    # Skip in CI environment (IP whitelist blocks GitHub Actions)
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        print('[CSQAQ] Skipping in CI (IP whitelist), will use local data')
        return None  # Return None to indicate skip, not empty
    
    all_alerts = []
    seen_ids = set()
    
    def fetch_page(sort_key, page):
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
            return items, sort_key, page
        except Exception as e:
            print(f'[WARN] CSQAQ {sort_key} page {page}: {e}', file=sys.stderr)
            return [], sort_key, page
    
    # 并发拉取所有页面
    tasks = []
    for sort_key in ('price_up_1d', 'price_down_1d'):
        for page in range(1, 4):
            tasks.append((sort_key, page))
    
    with ThreadPoolExecutor(max_workers=3) as executor:  # 降低并发避免 429
        futures = [executor.submit(fetch_page, sk, p) for sk, p in tasks]
        for future in as_completed(futures):
            items, sort_key, page = future.result()
            for item in items:
                item_id = item.get('id')
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                all_alerts.append({
                    'id': item_id,
                    'name': item.get('name', ''),
                    'exterior': item.get('exterior_localized_name', ''),
                    'rarity': item.get('rarity_localized_name', ''),
                    'price': float(item.get('buff_sell_price') or 0),
                    'rate_1': round(float(item.get('buff_price_chg') or item.get('sell_price_rate_1') or 0), 2),
                    'rate_7': round(float(item.get('sell_price_rate_7') or 0), 2),
                    'rate_30': round(float(item.get('sell_price_rate_30') or 0), 2),
                    'rank_num': item.get('rank_num', 0),
                    'img': item.get('img', ''),
                    'buff_sell': int(item.get('buff_sell_num') or 0),
                    'buff_buy': int(item.get('buff_buy_num') or 0),
                    'steam_buy': int(item.get('steam_buy_num') or 0),
                })

    all_alerts.sort(key=lambda x: abs(x.get('rate_1', 0)), reverse=True)
    _cached_alerts = all_alerts
    return all_alerts

# ═══════════════ RECOMMENDATIONS (复用缓存) ═══════════════
_cached_eco_full = None

def fetch_eco_full():
    """Fetch full ECO price list (36k+ items) - 带缓存"""
    global _cached_eco_full
    if _cached_eco_full is not None:
        return _cached_eco_full
    
    params = {
        'PartnerId': PARTNER_ID,
        'Timestamp': str(int(time.time())),
        'GameID': '730',
    }
    params['Sign'] = sign_eco(params)
    result = http_post('https://openapi.ecosteam.cn/Api/Market/GetHashNameAndPriceList', params, timeout=60)
    if str(result.get('ResultCode')) != '0':
        raise Exception(f"ECO ResultCode={result.get('ResultCode')}")
    _cached_eco_full = result.get('ResultData') or []
    return _cached_eco_full

def generate_recommendations(alerts=None):
    """Generate recommendations from CSQAQ alerts + ECO full data"""
    # 复用已获取的 alerts
    if alerts is None:
        alerts = fetch_csqaq_alerts(use_cache=True)
    
    # Fetch ECO full price list
    eco_items = fetch_eco_full()

    # Normalize names for matching
    def norm(s):
        return s.lower().replace(' ', '').replace('|', '').replace('(', '').replace(')', '').replace('-', '')

    # Build CSQAQ lookup
    csq_map = {}
    for a in alerts:
        key = norm(a.get('name', ''))
        if key:
            csq_map[key] = a

    # Merge ECO + CSQAQ
    merged = []
    for item in eco_items:
        gn = item.get('GoodsName', '')
        key = norm(gn)
        csq = csq_map.get(key, {})
        price = float(item.get('Price') or 0)
        if price < 10:
            continue
        merged.append({
            'name': gn,
            'hash_name': item.get('HashName', ''),
            'price': csq.get('price') or price,
            'rate_1': csq.get('rate_1', 0),
            'rate_7': csq.get('rate_7', 0),
            'eco_price': price,
            'eco_compre': float(item.get('MarketComprePrice') or 0),
            'eco_selling': int(item.get('SellingTotal') or 0),
            'eco_qg_total': int(item.get('QGTotal') or 0),
            'buff_sell': csq.get('buff_sell', 0),
            'buff_buy': csq.get('buff_buy', 0),
            'steam_buy': csq.get('steam_buy', 0),
            'img': csq.get('img', ''),
        })

    recs = {'momentum': [], 'undervalued': [], 'oversold': [], 'scarce': []}

    # 🔥 Momentum: 趋势向上 (7日涨 + 1日涨)
    for m in merged:
        r7 = m.get('rate_7', 0)
        r1 = m.get('rate_1', 0)
        price = m.get('price', 0)
        # 追涨：7日涨>0% (中期趋势向上) 且 1日涨>0% (短期强势)
        if price > 30 and r7 > 0 and r1 > 0:
            m['_score'] = round(r7 + r1 * 2, 2)
            m['_reason'] = f'7日{r7:+.1f}% 1日{r1:+.1f}% 📈趋势向上'
            recs['momentum'].append(m)
    recs['momentum'].sort(key=lambda x: x['_score'], reverse=True)
    recs['momentum'] = recs['momentum'][:20]

    # 💎 Undervalued: ECO compre > price * 1.05
    for m in merged:
        ep = m.get('eco_price', 0)
        ec = m.get('eco_compre', 0)
        selling = m.get('eco_selling', 0)
        if ep > 50 and ec > ep * 1.05 and ec < ep * 2.0 and selling > 0 and selling < 200:
            ratio = round(ec / ep, 3)
            m['_score'] = ratio
            m['_reason'] = f'综合价/售价={ratio:.1%}'
            recs['undervalued'].append(m)
    recs['undervalued'].sort(key=lambda x: x['_score'], reverse=True)
    recs['undervalued'] = recs['undervalued'][:20]

    # 📉 Oversold: 7d down > 8% with buy orders
    for m in merged:
        if m.get('rate_7', 0) < -8 and m.get('eco_qg_total', 0) > 0 and m.get('price', 0) > 50:
            m['_score'] = abs(m['rate_7'])
            recs['oversold'].append(m)
    recs['oversold'].sort(key=lambda x: x['_score'], reverse=True)
    recs['oversold'] = recs['oversold'][:20]

    # ⚡ Scarce: BUFF buy/sell ratio high
    for m in merged:
        name_lower = m.get('name', '').lower()
        if any(kw in name_lower for kw in ('武器箱', '钥匙', '箱', 'key', 'case')):
            continue
        buff_sell = m.get('buff_sell', 0)
        buff_buy = m.get('buff_buy', 0)
        price = m.get('price', 0) or m.get('eco_price', 0)
        if price < 20:
            continue
        if buff_sell > 0 and buff_buy > 0:
            ratio = buff_buy / buff_sell
            if ratio >= 0.15 and buff_sell < 500:
                m['_score'] = round(ratio, 2)
                m['_reason'] = f'BUFF求购{buff_buy}/在售{buff_sell}={ratio:.0%}'
                recs['scarce'].append(m)
    recs['scarce'].sort(key=lambda x: x['_score'], reverse=True)
    recs['scarce'] = recs['scarce'][:20]

    # Clean internal fields
    for r in recs.values():
        for item in r:
            item.pop('_score', None)
            item.pop('_reason', None)

    return recs

# ═══════════════ STEAMDT K-LINES (optional) ═══════════════
def fetch_steamdt_klines(items_list):
    """Fetch K-line data from SteamDT if API key is valid"""
    if not STEAM_KEY or STEAM_KEY == 'test_key':
        print('[INFO] SteamDT key not configured, skipping K-lines')
        return {}

    try:
        test = http_get(
            'https://open.steamdt.com/open/cs2/v1/price/single?marketHashName=AK-47%20%7C%20Redline%20(Field-Tested)',
            headers={'Authorization': f'Bearer {STEAM_KEY}'}
        )
        if not test.get('success'):
            print(f'[WARN] SteamDT key invalid (code={test.get("errorCode")}), skipping')
            return {}
    except Exception as e:
        print(f'[WARN] SteamDT unreachable: {e}, skipping')
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
        time.sleep(0.3)

    return kline_data

# ═══════════════ FILE I/O (track dirty state) ═══════════════
def read_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def write_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    dirty_files.add(os.path.basename(path))

# ═══════════════ PUSH (single atomic commit) ═══════════════
def push_all():
    """Push all dirty files in a single commit — avoids SHA conflicts"""
    if not dirty_files:
        print('[INFO] No files changed, skipping push')
        return

    if os.environ.get('GITHUB_ACTIONS') and GH_TOKEN:
        # CI: use GitHub Contents API — push files one by one, each getting fresh SHA
        for filename in sorted(dirty_files):
            path = os.path.join(DATA_DIR, filename)
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            github_push_file(filename, content, f'chore: update {", ".join(sorted(dirty_files))} {time.strftime("%m-%d %H:%M")}')
    else:
        # Local: single git commit + push
        git_push_locally(sorted(dirty_files), f'chore: update {", ".join(sorted(dirty_files))} {time.strftime("%Y-%m-%d %H:%M")}')

def github_push_file(path, content_str, message):
    """Push a single file via GitHub Contents API"""
    if not GH_TOKEN:
        print(f'[INFO] No GitHub token, skipping push of {path}')
        return False
    api_url = f'https://api.github.com/repos/{REPO}/contents/{path}'
    headers = {
        'Authorization': f'token {GH_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
    }
    # Always get fresh SHA before push
    sha = None
    try:
        req = urllib.request.Request(f'{api_url}?ref=main', headers=headers)
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            sha = json.loads(r.read().decode())['sha']
    except Exception:
        pass

    b64 = base64.b64encode(content_str.encode('utf-8')).decode('ascii')
    body_dict = {'message': message, 'content': b64, 'branch': 'main'}
    if sha:
        body_dict['sha'] = sha

    req = urllib.request.Request(api_url, data=json.dumps(body_dict).encode('utf-8'), headers=headers, method='PUT')
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            result = json.loads(r.read().decode())
            print(f'[OK] Pushed {path}: {result["commit"]["sha"][:8]}')
            return True
    except urllib.error.HTTPError as e:
        err = e.read().decode()[:300]
        print(f'[ERROR] Push {path}: HTTP {e.code}: {err}', file=sys.stderr)
        return False

def git_push_locally(files, message):
    """Push via local git in a single commit"""
    for f in files:
        subprocess.run(['git', 'add', f], check=True, cwd=DATA_DIR)
    subprocess.run(['git', 'commit', '-m', message], check=True, cwd=DATA_DIR)
    subprocess.run(['git', 'push'], check=True, cwd=DATA_DIR)
    print(f'[OK] Git pushed: {message}')

# ═══════════════ MAIN ═══════════════
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'

    print(f'=== CS2 Dashboard Update ({mode}) ===')

    # ── Update ECO prices → holdings.json ──
    if mode in ('all', 'prices'):
        holdings_path = os.path.join(DATA_DIR, 'holdings.json')
        holdings = read_json(holdings_path)

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

        write_json(holdings_path, holdings)

        pnl = total_market - total_cost
        pnl_pct = pnl / total_cost * 100 if total_cost else 0
        print(f'[ECO] Updated {updated}/{len(hash_names)} | Cost={total_cost:.0f} Market={total_market:.0f} PnL={pnl:+.0f} ({pnl_pct:+.1f}%)')

    # ── Update CSQAQ alerts → market.json ──
    alerts_data = None
    if mode in ('all', 'alerts'):
        print('[CSQAQ] Fetching alerts...')
        try:
            alerts_data = fetch_csqaq_alerts()
            if alerts_data is None:
                # CI environment skip - preserve existing alerts
                print('[CSQAQ] Skipped (CI), preserving existing alerts')
            else:
                print(f'[CSQAQ] Got {len(alerts_data)} alerts')
                market_path = os.path.join(DATA_DIR, 'market.json')
                market = read_json(market_path)
                market['alerts'] = alerts_data
                market['alerts_updated'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                write_json(market_path, market)
        except Exception as e:
            print(f'[CSQAQ] Failed: {e}', file=sys.stderr)

    # ── Update SteamDT K-lines (optional) ──
    if mode in ('all', 'klines') and STEAM_KEY:
        print('[SteamDT] Fetching K-lines...')
        try:
            market_path = os.path.join(DATA_DIR, 'market.json')
            market = read_json(market_path)
            items_list = market.get('items', [])
            kline_data = fetch_steamdt_klines(items_list)
            if kline_data:
                for item in items_list:
                    name = item.get('name_en') or item.get('name', '')
                    if name in kline_data:
                        item['kline'] = kline_data[name]
                market['items'] = items_list
                write_json(market_path, market)
        except Exception as e:
            print(f'[SteamDT] K-lines failed: {e}', file=sys.stderr)

    # ── Update Recommendations (复用 alerts) ──
    if mode in ('all', 'alerts'):
        print('[REC] Generating recommendations...')
        try:
            recs = generate_recommendations(alerts=alerts_data)
            total = sum(len(v) for v in recs.values())
            print(f'[REC] {total} recommendations')

            market_path = os.path.join(DATA_DIR, 'market.json')
            market = read_json(market_path)
            market['recommendations'] = recs
            write_json(market_path, market)
        except Exception as e:
            print(f'[REC] Failed: {e}', file=sys.stderr)

    # ── Push all dirty files at once ──
    push_all()
    print('=== Done ===')

if __name__ == '__main__':
    main()
