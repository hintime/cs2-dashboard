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
import json, time, base64, urllib.request, urllib.error, subprocess, os, sys, ssl, gzip
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
    print(f"[DEBUG] ECO_PRIVATE_KEY_B64 from env: {len(key_b64) if key_b64 else 0} chars, starts: {key_b64[:20] if key_b64 else 'None'}")
    if not key_b64:
        key_path = os.path.join(DATA_DIR, 'eco_private_key.txt')
        if os.path.exists(key_path):
            with open(key_path, 'r') as f:
                key_b64 = f.read().strip()
        else:
            raise FileNotFoundError('ECO private key not found')
    pem = '-----BEGIN RSA PRIVATE KEY-----\n' + key_b64 + '\n-----END RSA PRIVATE KEY-----'
    print(f"[DEBUG] PEM header: {pem[:40]}")
    print(f"[DEBUG] PEM length: {len(pem)}")
    _eco_key = RSA.import_key(pem)
    print(f"[DEBUG] RSA import_key succeeded, key size: {_eco_key.size_in_bits()} bits")
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
                raw = r.read()
                if raw[:2] == b'\x1f\x8b':
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode('utf-8'))
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
                raw = r.read()
                if raw[:2] == b'\x1f\x8b':
                    raw = gzip.decompress(raw)
                return json.loads(raw.decode('utf-8'))
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
                if raw[:2] == b'\x1f\x8b':
                    raw = gzip.decompress(raw)
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

# ═══════════════ 排除规则（不感兴趣的饰品类型） ═══════════════
_EXCLUDE_PREFIXES = ('StatTrak™ ', 'StatTrak ')
_EXCLUDE_EXTERIORS = {'破损不堪', '战痕累累'}

def _filter_excluded(items):
    """排除 StatTrak / 破损不堪(BS) / 战痕累累(WW) 饰品"""
    return [i for i in items
            if not any(i.get('name','').startswith(p) for p in _EXCLUDE_PREFIXES)
            and i.get('exterior','') not in _EXCLUDE_EXTERIORS]

# ═══════════════ CSQAQ ALERTS (支持 skill 调用 + proxy) ═══════════════
_cached_alerts = None  # 全局缓存，供 recommendations 复用
# Skill 路径：workspace/skills/csqaq-market-lookup/
CSQAQ_SKILL_PATH = os.path.join(os.path.dirname(DATA_DIR), 'skills', 'csqaq-market-lookup', 'scripts', 'csqaq_api.py')

# Proxy support for CI environments (bypasses IP whitelist)
CSQAQ_PROXY_URL = os.environ.get('CSQAQ_PROXY_URL', '').rstrip('/')

def _fetch_csqaq_direct(sort_key, page):
    """直接调用 CSQAQ API（原有逻辑）"""
    body = {
        'page_index': page,
        'page_size': 50,
        'filter': {'type': ['sticker', 'normal'], 'sort': [sort_key]},
        'show_recently_price': True
    }
    api_url = 'https://api.csqaq.com/api/v1/info/get_rank_list'
    if CSQAQ_PROXY_URL:
        api_url = f'{CSQAQ_PROXY_URL}/api/v1/info/get_rank_list'
    try:
        d = http_post_raw(
            api_url,
            body,
            headers={'ApiToken': CSQ_KEY},
            timeout=15
        )
        items = d.get('data', {})
        if isinstance(items, dict):
            items = items.get('data', [])
        return items
    except Exception as e:
        print(f'[WARN] CSQAQ {sort_key} page {page}: {e}', file=sys.stderr)
        return []

def fetch_csqaq_via_skill(sort_key='price_up_1d', page=1, page_size=50):
    """通过 csqaq-market-lookup skill 获取排行榜数据"""
    if not os.path.exists(CSQAQ_SKILL_PATH):
        print(f'[CSQAQ] Skill not found: {CSQAQ_SKILL_PATH}', file=sys.stderr)
        return []
    
    # 构建 JSON body 并写入临时文件
    body = {
        'page_index': page,
        'page_size': page_size,
        'filter': {'type': ['sticker', 'normal'], 'sort': [sort_key]},
        'show_recently_price': True
    }
    body_file = os.path.join(DATA_DIR, '_csqaq_body.json')
    with open(body_file, 'w', encoding='utf-8') as f:
        json.dump(body, f, ensure_ascii=False)
    
    # 调用 skill 的脚本（使用 --body-file 传递 JSON）
    try:
        env = os.environ.copy()
        env['CSQAQ_API_TOKEN'] = CSQ_KEY
        
        result = subprocess.run(
            ['python', CSQAQ_SKILL_PATH, 'call',
             '--path', '/api/v1/info/get_rank_list',
             '--method', 'POST',
             '--body-file', body_file,
             '--api-token', CSQ_KEY],
            capture_output=True, timeout=30,
            env=env
        )
        
        # 删除临时文件
        try:
            os.remove(body_file)
        except:
            pass
        
        # 解析输出（跳过 [CALL] 和 [STATUS] 行）
        output = result.stdout.decode('gbk', errors='replace')
        lines = output.strip().split('\n')
        json_start = -1
        for i, line in enumerate(lines):
            # 跳过 skill CLI 的状态行
            if line.startswith('[CALL]') or line.startswith('[STATUS]'):
                continue
            if line.startswith('{') or line.startswith('['):
                json_start = i
                break
        
        if json_start < 0:
            print(f'[CSQAQ] No JSON in output: {output[:200]}', file=sys.stderr)
            return []
        
        json_text = '\n'.join(lines[json_start:])
        data = json.loads(json_text)
        
        # 提取数据
        items = data.get('data', {})
        if isinstance(items, dict):
            items = items.get('data', [])
        
        return items
    except Exception as e:
        print(f'[CSQAQ] Skill error: {e}', file=sys.stderr)
        return []

def fetch_csqaq_alerts(use_cache=True, use_skill='auto'):
    """Fetch price change rankings from CSQAQ (智能切换调用方式)
    
    Args:
        use_cache: 是否使用缓存
        use_skill: 'auto' (自动切换), True (强制 skill), False (强制直接调用)
    
    Returns:
        list: 异动数据列表，或 None (CI 环境跳过)
    """
    global _cached_alerts
    
    if use_cache and _cached_alerts is not None:
        return _cached_alerts
    
    # Proxy support for CI environments (bypasses IP whitelist)
    # Removed GITHUB_ACTIONS skip — with proxy URL, CI can now fetch alerts too
    all_alerts = []
    seen_ids = set()
    
    # 智能选择调用方式
    def smart_fetch(sort_key, page):
        """智能切换：优先直接调用，失败则切换到 skill"""
        if use_skill == True:
            # 强制使用 skill
            return fetch_csqaq_via_skill(sort_key, page)
        elif use_skill == False:
            # 强制使用直接调用
            return _fetch_csqaq_direct(sort_key, page)
        else:
            # 自动模式：先尝试直接调用，失败则切换到 skill
            try:
                items = _fetch_csqaq_direct(sort_key, page)
                if items:
                    return items
                print(f'[CSQAQ] Direct call returned empty, fallback to skill')
            except Exception as e:
                print(f'[CSQAQ] Direct call failed: {e}, fallback to skill')
            
            # 切换到 skill
            try:
                return fetch_csqaq_via_skill(sort_key, page)
            except Exception as e:
                print(f'[CSQAQ] Skill call also failed: {e}')
                return []
    
    # 加载历史数据，用于计算变化量
    history_file = os.path.join(DATA_DIR, 'history.json')
    history = {}
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                h = json.load(f)
                # 建立 id -> 数据 的映射
                for item in h.get('alerts', []):
                    history[item.get('id')] = item
        except:
            pass
    
    # 串行拉取所有页面
    for sort_key in ('price_up_1d', 'price_down_1d'):
        for page in range(1, 3):
            items = smart_fetch(sort_key, page)
            for item in items:
                item_id = item.get('id')
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                
                buff_sell = int(item.get('buff_sell_num') or 0)
                buff_buy = int(item.get('buff_buy_num') or 0)
                
                # 计算变化量（与上次数据对比）
                h = history.get(item_id, {})
                sell_chg = buff_sell - h.get('buff_sell', buff_sell)
                buy_chg = buff_buy - h.get('buff_buy', buff_buy)
                
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
                    'buff_sell': buff_sell,
                    'buff_buy': buff_buy,
                    'steam_buy': int(item.get('steam_buy_num') or 0),
                    'sell_chg': sell_chg,  # 在售变化量
                    'buy_chg': buy_chg,    # 求购变化量
                })
            time.sleep(0.3)

    all_alerts.sort(key=lambda x: abs(x.get('rate_1', 0)), reverse=True)
    all_alerts = _filter_excluded(all_alerts)
    _cached_alerts = all_alerts
    
    # 保存当前数据作为历史（用于下次对比）
    try:
        history_data = {
            'alerts': [{'id': a['id'], 'buff_sell': a['buff_sell'], 'buff_buy': a['buff_buy']} for a in all_alerts],
            'updated_at': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(history_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'[HISTORY] Save failed: {e}', file=sys.stderr)
    
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

    # Merge ECO + CSQAQ（排除 StatTrak / 破损不堪 / 战痕累累）
    EXCLUDE_PRE = ('StatTrak™ ', 'StatTrak ')
    EXCLUDE_EXT = {'破损不堪', '战痕累累'}
    merged = []
    for item in eco_items:
        gn = item.get('GoodsName', '')
        # 按名称前缀过滤 StatTrak
        if any(gn.startswith(p) for p in EXCLUDE_PRE):
            continue
        # 按外观关键字过滤（从名称括号内提取）
        ext_in_name = gn.split('(')[1].rstrip(')') if '(' in gn else ''
        if ext_in_name in EXCLUDE_EXT:
            continue
        key = norm(gn)
        csq = csq_map.get(key, {})
        price = float(item.get('Price') or 0)
        if price < 10:
            continue
        exterior = csq.get('exterior', '')
        if exterior in EXCLUDE_EXT:
            continue
        merged.append({
            'name': gn,
            'hash_name': item.get('HashName', ''),
            'exterior': exterior,
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

    recs = {'momentum': [], 'undervalued': [], 'oversold': [], 'scarce': [], 'golden_cross': []}

    # 🔥 Momentum: 趋势向上 (7日涨 + 1日涨，均线多头排列)
    for m in merged:
        r7 = m.get('rate_7', 0)
        r1 = m.get('rate_1', 0)
        price = m.get('price', 0)
        # 追涨：7日涨>0% (中期趋势向上) 且 1日涨>0% (短期强势)
        # 加入用户知识：均线多头排列时趋势更可靠
        if price > 30 and r7 > 0 and r1 > 0:
            m['_score'] = round(r7 + r1 * 2, 2)
            m['_reason'] = f'7日{r7:+.1f}% 1日{r1:+.1f}% 📈趋势向上'
            recs['momentum'].append(m)
    recs['momentum'].sort(key=lambda x: x['_score'], reverse=True)
    recs['momentum'] = recs['momentum'][:20]

    # ✨ Golden Cross: 均线金叉（5日上穿10日）+ 供需健康
    # 简化版：7日涨转正 + 1日涨明显 + 求购活跃
    for m in merged:
        r7 = m.get('rate_7', 0)
        r1 = m.get('rate_1', 0)
        price = m.get('price', 0)
        buff_buy = m.get('buff_buy', 0)
        buff_sell = m.get('buff_sell', 0)
        # 金叉信号：7日由负转正（拐点）+ 1日强势 + 供需比健康
        if price > 30 and -2 < r7 < 5 and r1 > 1:
            # 拐点信号，可能正在形成金叉
            sd_ratio = buff_buy / max(buff_sell, 1)
            if sd_ratio > 0.1:
                m['_score'] = round(r1 * 2 + sd_ratio * 10, 2)
                m['_reason'] = f'5日拐头向上 ⚡供需比{sd_ratio:.0%}'
                recs['golden_cross'].append(m)
    recs['golden_cross'].sort(key=lambda x: x['_score'], reverse=True)
    recs['golden_cross'] = recs['golden_cross'][:20]

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

    # 📉 Oversold: 7d down > 8% with buy orders（抄底机会）
    # 加入用户知识：超跌反弹信号，需有求购支撑
    for m in merged:
        r7 = m.get('rate_7', 0)
        price = m.get('price', 0)
        eco_qg = m.get('eco_qg_total', 0)
        buff_buy = m.get('buff_buy', 0)
        # 超跌信号：7日跌>8% + 有求购（说明有人愿意接盘）
        if r7 < -8 and price > 50:
            # 量化抄底信号强度
            support_score = eco_qg + buff_buy * 0.5
            if support_score > 0:
                m['_score'] = abs(r7) + support_score
                m['_reason'] = f'超跌{abs(r7):.1f}% 📉有{eco_qg+buff_buy}单求购托底'
                recs['oversold'].append(m)
    recs['oversold'].sort(key=lambda x: x['_score'], reverse=True)
    recs['oversold'] = recs['oversold'][:20]

    # ⚡ Scarce: BUFF buy/sell ratio high（供需异动）
    # 加入用户知识：稀缺性是价格上涨的核心动力
    for m in merged:
        name_lower = m.get('name', '').lower()
        # 排除武器箱和钥匙（用户知识：千百战系列陷阱）
        if any(kw in name_lower for kw in ('武器箱', '钥匙', '箱', 'key', 'case')):
            continue
        buff_sell = m.get('buff_sell', 0)
        buff_buy = m.get('buff_buy', 0)
        price = m.get('price', 0) or m.get('eco_price', 0)
        if price < 20:
            continue
        if buff_sell > 0 and buff_buy > 0:
            ratio = buff_buy / buff_sell
            # 用户知识：求购/在售比>=15%说明稀缺性突出
            if ratio >= 0.15 and buff_sell < 500:
                m['_score'] = round(ratio, 2)
                m['_reason'] = f'BUFF求购{buff_buy}/在售{buff_sell}={ratio:.0%}'
                recs['scarce'].append(m)
    recs['scarce'].sort(key=lambda x: x['_score'], reverse=True)
    recs['scarce'] = recs['scarce'][:20]

    # Clean internal fields (保留 _reason 给前端显示)
    for r in recs.values():
        for item in r:
            item.pop('_score', None)  # 只清理内部分数字段

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
        today = time.strftime('%Y-%m-%d')
        for item in items:
            hn = item.get('market_hash')
            if hn and hn in prices:
                new_price = prices[hn]
                old_price = item.get('price', 0)

                # 更新价格
                item['price'] = new_price
                updated += 1

                # 记录历史价格（用于计算涨跌率）
                history = item.get('price_history', [])

                # 如果今天已有记录，更新；否则追加
                found = False
                for h in history:
                    if h.get('date') == today:
                        h['price'] = new_price
                        found = True
                        break
                if not found:
                    history.append({'date': today, 'price': new_price})

                # 保留最近 60 天历史（足够算 rate_30）
                history.sort(key=lambda x: x['date'])
                item['price_history'] = history[-60:]

                # 计算涨跌率
                # rate_1: 相对上一次更新
                if old_price and old_price > 0:
                    item['rate_1'] = round((new_price - old_price) / old_price * 100, 2)
                else:
                    item['rate_1'] = 0

                # rate_7: 相对 7 天前
                hist = item['price_history']
                if len(hist) >= 2:
                    # 找 7 天前的记录
                    today_dt = time.strptime(today, '%Y-%m-%d')
                    for h in hist:
                        h_dt = time.strptime(h['date'], '%Y-%m-%d')
                        days_diff = (time.mktime(today_dt) - time.mktime(h_dt)) / 86400
                        if 6 <= days_diff <= 8 and h.get('price', 0) > 0:
                            item['rate_7'] = round((new_price - h['price']) / h['price'] * 100, 2)
                            break
                    else:
                        # 没找到 7 天前的，用最旧的记录估算
                        if hist[0].get('price', 0) > 0:
                            oldest = hist[0]
                            oldest_dt = time.strptime(oldest['date'], '%Y-%m-%d')
                            days = max(1, (time.mktime(today_dt) - time.mktime(oldest_dt)) / 86400)
                            rate_raw = (new_price - oldest['price']) / oldest['price'] * 100
                            # 归一化到 7 天
                            item['rate_7'] = round(rate_raw / days * 7, 2) if days > 0 else 0

                # rate_30: 相对 30 天前（同理）
                if len(hist) >= 2:
                    today_dt = time.strptime(today, '%Y-%m-%d')
                    for h in hist:
                        h_dt = time.strptime(h['date'], '%Y-%m-%d')
                        days_diff = (time.mktime(today_dt) - time.mktime(h_dt)) / 86400
                        if 28 <= days_diff <= 32 and h.get('price', 0) > 0:
                            item['rate_30'] = round((new_price - h['price']) / h['price'] * 100, 2)
                            break
                    else:
                        # 没找到 30 天前的，用最旧的记录估算
                        if hist[0].get('price', 0) > 0:
                            oldest = hist[0]
                            oldest_dt = time.strptime(oldest['date'], '%Y-%m-%d')
                            days = max(1, (time.mktime(today_dt) - time.mktime(oldest_dt)) / 86400)
                            rate_raw = (new_price - oldest['price']) / oldest['price'] * 100
                            # 归一化到 30 天
                            item['rate_30'] = round(rate_raw / days * 30, 2) if days > 0 else 0

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
