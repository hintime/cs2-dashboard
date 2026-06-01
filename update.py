#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CS2 Dashboard 数据更新脚本 (优化版)
- ECOSteam API 获取持仓价格 → holdings.json
- BUFF 价格历史自算异动 → market.json (alerts)
- 可选：SteamDT K-lines (需有效 API Key)

优化：
- 并发请求（concurrent.futures）
- 数据缓存复用（alerts + recommendations 共享）
- 批量处理
"""
import json, time, base64, urllib.request, urllib.error, urllib.parse, subprocess, os, sys, ssl, gzip, socket, shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eco_sign import get_eco_key, sign_eco
import steam_market as sm
import eco_catalog
import recommend  # CSQAQ multi-platform price provider

# ═══════════════ CONFIG ═══════════════
PARTNER_ID = 'da740aa96cc14cc594371f95469c90ac'
# CSQAQ removed — alerts now self-computed from BUFF price history
STEAM_KEY = os.environ.get('STEAMDT_KEY', '')
GH_TOKEN = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN', '')
ZHIPU_KEY = os.environ.get('ZHIPU_KEY', '981fb5b064af4d86896d804ddea2acbc.VmZsKxfM4fL4vefz')
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

# ═══════════════ HOSTS BYPASS ═══════════════
# Steam++ injects hosts entries pointing api.steampowered.com → 127.0.0.1
# We detect this and skip those requests fast instead of waiting 30s timeout
HOSTS_BLOCKED = set()  # cached blocked hosts

def _check_host_blocked(host):
    """Return True if host is redirected to 127.0.0.1 by hosts file."""
    if host in HOSTS_BLOCKED:
        return True
    try:
        ip = socket.gethostbyname(host)
        if ip == '127.0.0.1':
            HOSTS_BLOCKED.add(host)
            print(f'[HOSTS] {host} blocked by hosts file (127.0.0.1), skipping')
            return True
    except Exception:
        pass
    return False

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
_EXCLUDE_PREFIXES = ('StatTrak™ ', 'StatTrak ', 'Souvenir ')
_EXCLUDE_EXTERIORS = {'破损不堪', '战痕累累'}

def _filter_excluded(items):
    """排除 StatTrak / Souvenir(纪念品) / 破损不堪(BS) / 战痕累累(WW) 饰品"""
    return [i for i in items
            if not any(i.get('name','').startswith(p) for p in _EXCLUDE_PREFIXES)
            and i.get('exterior','') not in _EXCLUDE_EXTERIORS]

# ═══════════════ BUFF PRICE HISTORY & ALERTS (自计算) ═══════════════
_buff_history_cache = None

def load_buff_history():
    """Load BUFF price history from disk"""
    global _buff_history_cache
    if _buff_history_cache is not None:
        return _buff_history_cache
    history_file = os.path.join(DATA_DIR, 'buff_history.json')
    if os.path.exists(history_file):
        try:
            _buff_history_cache = read_json(history_file)
            return _buff_history_cache
        except:
            pass
    return {}

def save_buff_history(steamdt_prices):
    """Save hourly + daily BUFF/悠悠 snapshots to buff_history.json"""
    hour_key = time.strftime('%Y-%m-%dT%H:00')  # 小时级（异动）
    day_key = time.strftime('%Y-%m-%d')          # 日级（7日涨跌）
    history_file = os.path.join(DATA_DIR, 'buff_history.json')
    
    history = load_buff_history()
    
    # Keep last 48 hours + 15 days
    dates = sorted(history.keys(), reverse=True)
    keep = []
    for d in dates:
        if len(d) == 16 and len(keep) < 48:  # hourly: YYYY-MM-DDTHH:MM
            keep.append(d)
        elif len(d) == 10 and len(keep) < 48+15:  # daily: YYYY-MM-DD
            keep.append(d)
    for old_date in dates:
        if old_date not in keep:
            del history[old_date]
    
    # Save snapshot (BUFF + 悠悠) — both hourly and daily
    history[hour_key] = {}
    history[day_key] = {}
    for name, info in steamdt_prices.items():
        if isinstance(info, dict):
            entry = {
                'buff_sell': info.get('buff_sell', 0),
                'buff_buy': info.get('buff_buy', 0),
                'buff_sell_num': info.get('buff_sell_num', 0),
                'buff_buy_num': info.get('buff_buy_num', 0),
                'yyyp_sell': info.get('yyyp_sell', 0),
                'yyyp_sell_num': info.get('yyyp_sell_num', 0),
            }
            # 也从 platforms 取悠悠数据
            plats = info.get('platforms', {})
            if plats:
                yyyp = plats.get('yyyp', {})
                if yyyp:
                    if not entry['yyyp_sell']:
                        entry['yyyp_sell'] = yyyp.get('price', 0) or yyyp.get('sell_price', 0) or 0
                    if not entry['yyyp_sell_num']:
                        entry['yyyp_sell_num'] = yyyp.get('sell_num', 0) or yyyp.get('count', 0) or 0
            history[hour_key][name] = entry
            history[day_key][name] = entry
    
    write_json(history_file, history)
    _buff_history_cache = history
    y_c = sum(1 for v in history[hour_key].values() if v.get('yyyp_sell', 0) > 0)
    print(f'[HISTORY] Hour {hour_key} + Day {day_key}: {len(steamdt_prices)} items, {y_c} with 悠悠')
    return history

def compute_alerts(steamdt_prices):
    """Compute price change alerts from BUFF price history (replaces CSQAQ)
    
    Returns: list of alert dicts with name, price, rate_1, rate_7, etc.
    """
    # Lazy-load price_summary for fallback
    _ph_summary = None
    def _get_ph_summary(name):
        nonlocal _ph_summary
        if _ph_summary is None:
            ps_file = os.path.join(DATA_DIR, 'price_summary.json')
            if os.path.exists(ps_file):
                _ph_summary = read_json(ps_file) or {}
            else:
                _ph_summary = {}
        return _ph_summary.get(name, {})
    
    history = load_buff_history()
    if not history:
        print('[ALERTS] No history available, returning empty list')
        return []
    if not steamdt_prices:
        print('[ALERTS] No current prices, returning empty list')
        return []
    
    dates = sorted(history.keys())
    today = time.strftime('%Y-%m-%d')
    target_1d = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 86400))
    target_7d = time.strftime('%Y-%m-%d', time.gmtime(time.time() - 86400 * 7))
    
    # Find closest dates to 1d and 7d ago
    yest = None
    week = None
    for d in reversed(dates):
        if d < today:
            if yest is None:
                yest = d
            if d <= target_7d and week is None:
                week = d
    if yest is None and len(dates) >= 2:
        yest = dates[-2]
    if week is None and len(dates) >= 7:
        week = dates[-7]
    
    if yest:
        print(f'[ALERTS] Using {yest} as 1d reference (target={target_1d})')
    if week:
        print(f'[ALERTS] Using {week} as 7d reference (target={target_7d})')
    
    alerts = []
    for name, info in steamdt_prices.items():
        if not isinstance(info, dict):
            continue
        current = info.get('buff_sell', 0)
        if current <= 0:
            continue
        
        prev_price = 0
        if yest and yest in history:
            prev = history[yest].get(name, {})
            if isinstance(prev, dict):
                prev_price = prev.get('buff_sell', 0)
        
        old_price = 0
        if week and week in history:
            old = history[week].get(name, {})
            if isinstance(old, dict):
                old_price = old.get('buff_sell', 0)
        
        rate_1 = round((current - prev_price) / prev_price * 100, 2) if prev_price > 0 else 0
        rate_7 = round((current - old_price) / old_price * 100, 2) if old_price > 0 else 0
        
        # Fallback: 如果 SteamDT 历史不足，从 price_history.json 的 ECO 数据补
        if rate_7 == 0 or rate_1 == 0:
            ph = _get_ph_summary(name)
            if ph:
                if rate_7 == 0 and ph.get('change_7d'):
                    rate_7 = round(ph['change_7d'], 2)
                if rate_1 == 0 and ph.get('change_1d'):
                    rate_1 = round(ph['change_1d'], 2)
        
        alerts.append({
            'name': name,
            'price': current,
            'rate_1': rate_1,
            'rate_7': rate_7,
            'buff_sell': info.get('buff_sell_num', 0),
            'buff_buy': info.get('buff_buy_num', 0),
            'buff_price': current,
            'steam_buy': 0,
            'img': '',
        })
    
    # Sort by absolute rate_1 (biggest changers first)
    alerts.sort(key=lambda x: abs(x.get('rate_1', 0)), reverse=True)
    print(f'[ALERTS] Computed {len(alerts)} items from history ({len(dates)} days)')
    return alerts

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

def generate_recommendations(alerts=None, steamdt_prices=None):
    """Dual-scoring recommendation engine.
    ECO score (0-100): supply/demand + valuation from eco_tracked.json
    BUFF score (0-100): price premium + order book from SteamDT data
    Combined: max(ECO_score, BUFF_score), top 30, threshold >= 25
    Returns: {'all': list of sorted recommendations}
    """
    # Load ECO tracked items (built by eco_catalog.py)
    tracked_path = os.path.join(DATA_DIR, 'eco_tracked.json')
    if not os.path.exists(tracked_path):
        print('[REC] eco_tracked.json not found, no recommendations')
        return {'all': []}

    with open(tracked_path, 'r', encoding='utf-8') as f:
        tracked = json.load(f)
    print(f'[REC] Loaded {len(tracked)} items from eco_tracked.json')

    # 排除 StatTrak / Souvenir(纪念品) / BS(破损不堪/战痕累累) 等不想要的
    _EXCLUDE_PREFIXES = ('StatTrak™ ', 'StatTrak ', 'Souvenir ')
    _EXCLUDE_EXTERIORS = ('Battle-Scarred', '战痕累累', '破损不堪')
    before = len(tracked)
    tracked = [i for i in tracked
               if not any(i.get('HashName','').startswith(p) for p in _EXCLUDE_PREFIXES)
               and not any(e in (i.get('HashName','') + i.get('GoodsName','')) for e in _EXCLUDE_EXTERIORS)]
    if len(tracked) < before:
        print(f'[REC] Filtered out {before - len(tracked)} excluded items ({len(tracked)} remaining)')

    # Build BUFF price lookup from steamdt_prices (32 holdings + enriched catalog)
    buff_map = {}
    if steamdt_prices:
        buff_map = steamdt_prices
    # Also check items that have BUFF data in eco_tracked.json (ENRICH_BUFF=1)
    for item in tracked:
        hn = item.get('HashName', '')
        if hn not in buff_map and item.get('buff_sell', 0) > 0:
            buff_map[hn] = {
                'buff_sell': item.get('buff_sell', 0),
                'buff_buy': item.get('buff_buy', 0),
                'buff_sell_num': item.get('buff_sell_num', 0),
                'buff_buy_num': item.get('buff_buy_num', 0),
            }
    print(f'[REC] BUFF prices available for {len(buff_map)} items')

    all_recs = []

    for item in tracked:
        hn = item.get('HashName', '')
        gn = item.get('GoodsName', hn)
        price = float(item.get('Price') or 0)
        compre = float(item.get('MarketComprePrice') or 0)
        selling = int(item.get('SellingTotal') or 0)
        qg_total = int(item.get('QGTotal') or 0)
        qg_max = float(item.get('QGMaxPrice') or 0)

        if price < 20:  # Skip items below ¥20 (filter cheap stickers/graffiti)
            continue

        # ══════════ ECO Score (0-100): supply/demand + valuation ══════════
        eco_score = 0.0
        eco_reasons = []

        # 1. Undervaluation: MarketComprePrice >> Price (35 pts max)
        if compre > 0 and price > 0:
            underval_pct = (compre - price) / price * 100
            if underval_pct > 5:  # Require >5% gap
                uv = min(underval_pct * 0.7, 35)
                eco_score += uv
                if uv > 7:
                    eco_reasons.append('ECO低估{}% (综合{:.0f} vs 现价{:.0f})'.format(
                        round(underval_pct), compre, price))

        # 2. Scarcity: buy/sell ratio (20 pts max, logarithmic to prevent domination by stickers)
        if selling > 0 and qg_total > 0:
            import math
            ratio = qg_total / selling
            if ratio > 0.05:
                sc = min(math.log(ratio + 1) * 10, 20)
                eco_score += sc
                if sc > 5:
                    eco_reasons.append('稀缺求/售比{:.0%} (求{} 售{})'.format(ratio, qg_total, selling))

        # 3. Demand strength: buy price vs sell price (15 pts max)
        if qg_max > 0 and price > 0:
            demand = qg_max / price
            if demand > 0.5:
                dm = min(demand * 15, 15)
                eco_score += dm
                if dm > 5:
                    eco_reasons.append('求购活跃 出价{:.0f} vs 售价{:.0f}'.format(qg_max, price))

        # ══════════ BUFF Score (0-100): price premium + order book ══════════
        buff_score = 0.0
        buff_reasons = []
        bd = buff_map.get(hn, {})
        if bd:
            bs = bd.get('buff_sell', 0) or 0
            bb = bd.get('buff_buy', 0) or 0
            bsn = bd.get('buff_sell_num', 0) or 0
            bbn = bd.get('buff_buy_num', 0) or 0

            # 1. BUFF premium over ECO price (30 pts max)
            if bs > 0 and price > 0:
                premium = (bs - price) / price * 100
                if premium > 3:
                    pr = min(premium * 0.7, 30)
                    buff_score += pr
                    if pr > 7:
                        buff_reasons.append('BUFF溢价{}% ({:.0f} vs ECO{:.0f})'.format(
                            round(premium), bs, price))

            # 2. BUFF buy/sell ratio (15 pts max)
            if bsn > 0 and bbn > 0:
                b_ratio = bbn / bsn
                if b_ratio > 0.05:
                    br = min(b_ratio * 15, 15)
                    buff_score += br
                    if br > 5:
                        buff_reasons.append('BUFF买/卖比{:.0%} (买{} 卖{})'.format(b_ratio, bbn, bsn))

            # 3. BUFF liquidity depth (10 pts max)
            if bsn > 0:
                liq = min(bsn / 500 * 10, 10)
                buff_score += liq

            # 4. BUFF buy power (bonus 5 pts)
            if bsn > 0 and bbn > 0:
                bp = min(bbn / (bsn + bbn) * 5, 5)
                buff_score += bp

        # ══════════ 悠悠有品 Score (bonus, 20 pts max) ══════════
        yyyp_sell = item.get('yyyp_sell', 0) or 0
        yyyp_sell_num = item.get('yyyp_sell_num', 0) or 0
        # 悠悠在售少于40件 → 不推荐
        if yyyp_sell_num > 0 and yyyp_sell_num < 40:
            continue
        if yyyp_sell > 0:
            # 5. 悠悠价格 vs ECO价格 (10 pts max)
            yyyp_premium = (yyyp_sell - price) / price * 100 if price > 0 else 0
            if yyyp_premium > 2:
                yp = min(yyyp_premium * 0.5, 10)
                buff_score += yp
                if yp > 4:
                    buff_reasons.append('悠悠溢价{}% ({:.0f} vs ECO{:.0f})'.format(
                        round(yyyp_premium, 1), yyyp_sell, price))

            # 6. 悠悠在售深度 (10 pts max) — 在售少说明稀缺
            if yyyp_sell_num > 0:
                scarce = min(max(0, (500 - yyyp_sell_num) / 500 * 10), 10)
                if scarce > 2:
                    buff_score += scarce
                    if scarce > 5:
                        buff_reasons.append('悠悠在售仅{}件'.format(yyyp_sell_num))

        # ══════════ Combined ══════════
        final_score = max(eco_score, buff_score)

        if final_score < 25:
            continue

        # Primary source determines category tag and reason
        if buff_score > eco_score and buff_reasons:
            tag = 'buff'
            tag_label = '多平台信号'
            signal_desc = '多平台热度高'
            primary_reasons = buff_reasons + eco_reasons[:1]
        else:
            tag = 'eco'
            tag_label = 'ECO信号'
            signal_desc = 'ECO供需失衡'
            primary_reasons = eco_reasons + buff_reasons[:1]

        # ── Build rich actionable reason ──
        combined_reason = ' | '.join(primary_reasons[:3]) if primary_reasons else ''
        
        # Build operation advice
        if tag == 'eco':
            # ECO signal: suggest buying at bid price
            suggest_bid = int(qg_max) if qg_max > 0 else int(price * 0.9)
            buy_advice_parts = []
            if selling > 0 and qg_total > 0:
                ratio = qg_total / selling
                if ratio > 3:
                    buy_advice_parts.append('需求旺盛，建议挂求购价¥{}买入'.format(suggest_bid))
                elif ratio > 1:
                    buy_advice_parts.append('供需偏紧，可挂求购价¥{}建仓'.format(suggest_bid))
                else:
                    buy_advice_parts.append('供需平衡，建议分批挂单买入')
            if compre > price:
                underval_pct = (compre - price) / price * 100
                if underval_pct > 10:
                    buy_advice_parts.append('综合评估价¥{:.0f}明显高于现价，性价比较高'.format(compre))
            if not buy_advice_parts:
                buy_advice_parts.append('建议分仓操作，单品种不超过10%仓位')
            buy_advice = ' | '.join(buy_advice_parts[:2])
        else:
            # BUFF/multi-platform signal (T+7 market, no arbitrage possible)
            buy_advice_parts = []
            if bs > 0 and price > 0:
                diff = (bs - price) / price * 100
                if diff > 5:
                    buy_advice_parts.append('多平台溢价{:.1f}%，市场热度较高'.format(abs(diff)))
                elif diff < -5:
                    buy_advice_parts.append('多平台折价{:.1f}%，ECO价格偏高需谨慎'.format(abs(diff)))
                else:
                    buy_advice_parts.append('多平台与ECO价差{:.1f}%，价格趋近合理'.format(abs(diff)))
            if bsn > 0:
                buy_advice_parts.append('多平台在售{}件，流动性{}'.format(bsn, '充裕' if bsn > 100 else '一般'))
            if not buy_advice_parts:
                buy_advice_parts.append('建议结合ECO供需数据综合判断')
            buy_advice = ' | '.join(buy_advice_parts[:2])

        reason = '{} | ECO分{:.0f}/BUFF分{:.0f}→综合{:.0f} | {} | 💡 {} | 建议分仓操作,单品<10%'.format(
            signal_desc, eco_score, buff_score, final_score, combined_reason, buy_advice)

        all_recs.append({
            'name': gn,
            'hash_name': hn,
            'price': price,
            'eco_score': round(eco_score, 1),
            'buff_score': round(buff_score, 1),
            'score': round(final_score, 1),
            'tag': tag,
            'tag_label': tag_label,
            'eco_price': price,
            'eco_compre': compre,
            'eco_selling': selling,
            'eco_qg_total': qg_total,
            'eco_qg_price': qg_max,
            'buff_sell': bd.get('buff_sell', 0) or 0,
            'buff_buy': bd.get('buff_buy', 0) or 0,
            'buff_sell_num': bd.get('buff_sell_num', 0) or 0,
            'buff_buy_num': bd.get('buff_buy_num', 0) or 0,
            'platforms': bd.get('platforms', {}),
            'yyyp_sell': item.get('yyyp_sell', 0) or 0,
            'yyyp_sell_num': item.get('yyyp_sell_num', 0) or 0,
            '_reason': reason,
            '_cat': tag,
        })

    # Sort by combined score, take top 30
    all_recs.sort(key=lambda x: x['score'], reverse=True)
    all_recs = all_recs[:30]

    eco_count = sum(1 for r in all_recs if r['tag'] == 'eco')
    buff_count = sum(1 for r in all_recs if r['tag'] == 'buff')
    print(f'[REC] {len(all_recs)} recommendations (ECO={eco_count}, BUFF={buff_count})')

    return {'all': all_recs}

# ═══════════════ STEAMDT K-LINES (optional) ═══════════════
def fetch_steamdt_klines(items_list):
    """Fetch K-line data from SteamDT if API key is valid"""
    if not STEAM_KEY or STEAM_KEY == 'test_key':
        print('[INFO] SteamDT key not configured, skipping K-lines')
        return {}

    try:
        # Test API key with a simple endpoint
        test = http_get(
            'https://open.steamdt.com/open/cs2/v1/price/single?marketHashName=AK-47%20%7C%20Redline%20(Field-Tested)',
            headers={'Authorization': f'Bearer {STEAM_KEY}'}
        )
        print(f'[SteamDT] Test response: success={test.get("success")}, errorCode={test.get("errorCode")}, errorMsg={test.get("errorMsg")}')
        if not test.get('success'):
            print(f'[WARN] SteamDT key invalid (code={test.get("errorCode")}, msg={test.get("errorMsg")}), skipping')
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
            if not resp.get('success'):
                print(f'  K-line API error for {name[:35]}: {resp.get("errorCode")} - {resp.get("errorMsg")}')
                continue
            if resp.get('data'):
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

# ═══════════════ STEAMDT PRICES (BUFF/悠悠有品/C5/IGXE) ═══════════════
def fetch_steamdt_prices(hash_names, verbose=True):
    """Fetch multi-platform prices from SteamDT, respecting API limits:
    - single API: 60次/分钟 → 间隔≥1秒（用于持仓≤32件）
    - batch API: 1次/分钟 → 批量100件（用于全量追踪）
    
    策略：有BUFF价格的饰品跳过不查（增量更新）
    """
    if not STEAM_KEY or STEAM_KEY == 'test_key':
        if verbose:
            print('[INFO] SteamDT key not configured, skipping BUFF prices')
        return {}
    if not hash_names:
        return {}

    import urllib.parse as _up
    import json as _json

    def _parse_buff(name, resp):
        """Parse a single item's platform data from SteamDT response."""
        if not resp.get('success'):
            return None
        platforms = resp.get('data', [])
        if not platforms:
            return None
        priority = {'BUFF': 0, 'UUYP': 1, 'C5': 2, 'YOUPIN': 3, 'IGXE': 4, 'STEAM': 5}
        best, best_prio = None, 99
        for p_inner in platforms:
            plat = p_inner.get('platform', '')
            sell = float(p_inner.get('sellPrice', 0))
            buy = float(p_inner.get('biddingPrice', 0))
            if sell <= 0 and buy <= 0:
                continue
            prio = priority.get(plat.upper(), 50)
            if prio < best_prio:
                best_prio = prio
                best = {
                    'buff_sell': sell, 'buff_buy': buy,
                    'buff_sell_num': int(p_inner.get('sellCount', 0)),
                    'buff_buy_num': int(p_inner.get('biddingCount', 0)),
                    'update_time': p_inner.get('updateTime', 0),
                    'source': plat, 'buff_source': plat,
                }
                # 找到BUFF就是最优，其他平台不关我们事了
                if prio == 0:
                    break
        return best

    # ── 持仓（≤32件）：single API，间隔≥1秒 ──
    if len(hash_names) <= 32:
        prices = {}
        for i, name in enumerate(hash_names):
            try:
                time.sleep(1.0)  # 60次/分钟 → 1秒间隔
                url = f'https://open.steamdt.com/open/cs2/v1/price/single?marketHashName={_up.quote(name)}'
                resp = http_get(url, headers={'Authorization': f'Bearer {STEAM_KEY}'}, timeout=15)
                data = _parse_buff(name, resp)
                if data:
                    prices[name] = data
                    if verbose and len(prices) <= 3:
                        print(f'  [SteamDT] {name[:40]}: {data["source"]} sell={data["buff_sell"]:.2f}')
            except Exception:
                pass
        if verbose:
            print(f'[SteamDT] Got {len(prices)}/{len(hash_names)} prices')
        return prices

    # ── 全量追踪：batch API，每分钟1次，每次100件 ──
    # 循环分批查询所有物品（每批100件，间隔65秒，遵守1次/分钟限制）
    prices = {}
    total_batches = (len(hash_names) + 99) // 100
    # 自动模式下每次最多跑 5 批（约5分钟），避免阻塞下次任务
    # 交互模式下跑满全部
    import os as _os
    is_scheduled = _os.environ.get('SCHEDULED_RUN', '').strip() == '1'
    max_batches = 5 if is_scheduled else total_batches
    try:
        for batch_idx in range(min(max_batches, total_batches)):
            start_i = batch_idx * 100
            batch = hash_names[start_i:start_i + 100]
            if not batch:
                break
            if verbose or batch_idx == 0:
                print(f'[SteamDT] Batch {batch_idx+1}/{total_batches}: {len(batch)} items...')
            if batch_idx > 0:
                time.sleep(65.0)  # 遵守1次/分钟限制（加5秒缓冲）
            body = _json.dumps({'marketHashNames': batch}).encode('utf-8')
            resp = http_post_raw(
                'https://open.steamdt.com/open/cs2/v1/price/batch',
                body,
                headers={'Authorization': f'Bearer {STEAM_KEY}', 'Content-Type': 'application/json'},
                timeout=30,
            )
            result = _json.loads(resp)
            if result.get('success'):
                for item_data in result.get('data', []):
                    hn = item_data.get('marketHashName', '')
                    if hn and item_data.get('dataList'):
                        data = _parse_buff(hn, {'success': True, 'data': item_data['dataList']})
                        if data:
                            prices[hn] = data
            if verbose:
                print(f'[SteamDT] Batch {batch_idx+1} got prices for batch')
        if verbose:
            print(f'[SteamDT] Total from {len(hash_names)} items: {len(prices)} prices ({len(prices)/max(len(hash_names),1)*100:.1f}% coverage)')
    except Exception as e:
        if verbose:
            print(f'[SteamDT] Batch failed: {e}', file=sys.stderr)

    return prices

# ═══════════════ STEAM NEWS (fetch server-side, avoid CORS) ═══════════════
def fetch_steam_news():
    """Fetch CS2 Steam news → saves news.json (Chinese translated)"""
    try:
        if _check_host_blocked('api.steampowered.com'):
            print('[NEWS] Skipped (Steam API blocked by hosts file)')
            return None
        # Request Chinese localization from Steam API
        url = 'https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=730&count=12&maxlength=300&feeds=steam_community_announcements&l=schinese'
        r = http_get(url, timeout=8)
        raw = (r.get('appnews', {}) or {}).get('newsitems', [])
        if not raw:
            print('[NEWS] Empty response from Steam API')
            return None

        def strip_html(s):
            import re
            s = s.replace('{STEAM_CLAN_IMAGE}', '')
            s = re.sub(r'\{[A-Z_]+\}[^\s]*', '', s)  # {LINK_REMOVED} etc
            s = re.sub(r'\\[A-Za-z]+', '', s)          # \Cache \NIGHT \Fixed etc
            s = re.sub(r'https?://\S+', '', s)          # strip raw image URLs
            s = re.sub(r'<[^>]+>', '', s)
            s = s.replace('\n', ' ').replace('\r', ' ').strip()
            return s[:200]

        def has_cjk(s):
            return any('\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' for c in s)

        def translate_text(text):
            """Translate EN→ZH via MyMemory API (fallback: Google Translate)"""
            if not text or has_cjk(text):
                return text
            # Try MyMemory first (free, no key, reliable in China)
            try:
                turl = 'https://api.mymemory.translated.net/get?q=' + urllib.parse.quote(text[:500]) + '&langpair=en|zh'
                resp = http_get(turl, timeout=20)
                if isinstance(resp, dict):
                    rd = resp.get('responseData', {})
                    translated = rd.get('translatedText', '')
                    match = rd.get('match', 0)
                    if translated and translated != text and match >= 0.5:
                        return translated
            except:
                pass
            # Fallback: Google Translate (may be blocked)
            try:
                turl = 'https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q=' + urllib.parse.quote(text[:200])
                resp = http_get(turl, timeout=20)
                if isinstance(resp, list) and len(resp) > 0 and isinstance(resp[0], list) and len(resp[0]) > 0:
                    translated = resp[0][0][0]
                    if translated and translated != text:
                        return translated
            except:
                pass
            return text

        # Chinese source labels
        LABEL_CN = {
            'Community Announcements': '社区公告',
            'Steam Community Announcements': 'Steam 社区公告',
            'Steam': 'Steam',
        }

        news_items = []
        for n in raw:
            title = n.get('title', '')
            body = strip_html(n.get('contents', ''))
            source = n.get('feedlabel', 'Steam')
            news_items.append({
                'title': translate_text(title),
                'body': translate_text(body),
                'url': n.get('url', 'https://steamcommunity.com/app/730/'),
                'date': n.get('date', 0),
                'source': LABEL_CN.get(source, source),
            })

        # Split: patches (update notes) vs general news
        patches = [x for x in news_items if '更新' in x['title'] or 'Update' in x['title'] or '更新' in x['title']]
        general = [x for x in news_items if x not in patches]

        result = {
            'news': general + patches,
            'updates': patches[:8],
            'updated': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        print(f'[NEWS] Fetched {len(news_items)} items ({len(general)} news + {len(patches)} updates)')
        return result
    except Exception as e:
        print(f'[NEWS] Failed: {e}', file=sys.stderr)
        return None

# ═══════════════ FILE I/O (track dirty state) ═══════════════
def read_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def write_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    dirty_files.add(os.path.basename(path))

def generate_price_summary():
    """从 price_history.json 衍生 price_summary.json"""
    ph_file = os.path.join(DATA_DIR, 'price_history.json')
    if not os.path.exists(ph_file):
        print('[SUMMARY] price_history.json not found, skip')
        return
    ph = read_json(ph_file)
    summary = {}
    for name, h in ph.items():
        if not isinstance(h, dict): continue
        eco = h.get('eco', [])
        if not eco: continue
        daily = {}
        for pt in eco:
            day = pt['t'][:10]
            daily[day] = daily.get(day, []) + [pt['p']]
        s = {'first': eco[0]['p'], 'last': eco[-1]['p'], 'days': (len(eco)//24) if len(eco)>24 else 1}
        s['daily_avg'] = {d: round(sum(v)/len(v),2) for d,v in list(daily.items())[-30:]}
        dates = sorted(daily.keys())
        s['change_7d'] = 0; s['change_30d'] = 0
        if dates:
            avg1 = sum(daily[dates[-1]])/len(daily[dates[-1]])
            if len(dates) >= 7:
                avg7 = sum(daily[dates[-7]])/len(daily[dates[-7]])
                s['change_7d'] = round((avg1 - avg7) / avg7 * 100, 2) if avg7 > 0 else 0
            if len(dates) >= 30:
                avg30 = sum(daily[dates[-30]])/len(daily[dates[-30]])
                s['change_30d'] = round((avg1 - avg30) / avg30 * 100, 2) if avg30 > 0 else 0
        summary[name] = s
    write_json(os.path.join(DATA_DIR, 'price_summary.json'), summary)
    print(f'[SUMMARY] {len(summary)} items')

def generate_ai_analysis():
    """智谱AI全量持仓分析 — JSON结构化 + 批量单次调用 + 联网搜索"""
    if not ZHIPU_KEY or ZHIPU_KEY == 'test_key':
        print('[AI] No Zhipu key, skip')
        return
    holdings = read_json(os.path.join(DATA_DIR, 'holdings.json'))
    items = holdings.get('items', []) if isinstance(holdings, dict) else holdings
    if not items:
        print('[AI] No holdings, skip')
        return
    items = sorted(items, key=lambda x: x.get('cost', 0) * x.get('qty', 1), reverse=True)
    total = len(items)
    
    # ① 联网搜索 CS2 最新市场新闻
    news_context = ''
    try:
        news_data = json.dumps({
            'model': 'glm-4.7-flash',
            'messages': [{'role': 'user', 'content': '搜索2026年6月CS2饰品市场最新动态，包括：CS2大行动更新、箱子新出、饰品价格异动、BUFF市场热点。用中文总结3条最重要的信息。'}],
            'tools': [{'type': 'web_search', 'web_search': {'search_query': 'CS2 skins market June 2026 latest news'}}],
            'max_tokens': 500, 'temperature': 0.3
        }).encode('utf-8')
        req = urllib.request.Request('https://open.bigmodel.cn/api/paas/v4/chat/completions', data=news_data, headers={
            'Authorization': f'Bearer {ZHIPU_KEY}', 'Content-Type': 'application/json'
        })
        resp = urllib.request.urlopen(req, timeout=30)
        nr = json.loads(resp.read().decode('utf-8'))
        news_context = nr['choices'][0]['message'].get('content', '')
        print(f'[AI] News: {news_context[:80]}...')
    except Exception as e:
        print(f'[AI] News search failed: {e}')

    # ② 构建批量分析 Prompt（所有持仓编入一张表）
    items_text = '\n'.join([
        f'{i+1}. {it.get("name","")} | 现价¥{it.get("price",0):.0f} | 成本¥{it.get("cost",0):.0f} | 盈亏{((it.get("price",0)-it.get("cost",0))/it.get("cost",0)*100 if it.get("cost",0)>0 else 0):+.1f}% | 7日{it.get("rate_7",0):+.1f}% | 30日{it.get("rate_30",0):+.1f}%'
        for i, it in enumerate(items)
    ])
    market_context = f'市场新闻: {news_context}' if news_context else ''
    prompt = f'''分析以下{total}件CS2饰品持仓，每件给出操作建议。

{items_text}

{market_context}

请严格返回JSON对象（不要markdown代码块），格式：{{"items":{{"饰品名":{{"verdict":"买入/持有/减仓/观望","confidence":80,"reason":"一句话","risk":"一句话","entryLow":价格下限,"entryHigh":价格上限}},...}},"summary":"一句话市场总结"}}'''
    
    try:
        data = json.dumps({
            'model': 'glm-4.7-flash',
            'messages': [
                {'role': 'system', 'content': '你是CS2饰品投资分析师。只返回JSON，不返回任何其他内容。'},
                {'role': 'user', 'content': prompt}
            ],
            'response_format': {'type': 'json_object'},
            'thinking': {'type': 'enabled'},
            'max_tokens': 4096, 'temperature': 0.3
        }).encode('utf-8')
        req = urllib.request.Request('https://open.bigmodel.cn/api/paas/v4/chat/completions', data=data, headers={
            'Authorization': f'Bearer {ZHIPU_KEY}', 'Content-Type': 'application/json'
        })
        resp = urllib.request.urlopen(req, timeout=120)
        r = json.loads(resp.read().decode('utf-8'))
        raw = r['choices'][0]['message']['content']
        
        # ③ 解析 JSON 响应
        parsed = json.loads(raw)
        results = parsed.get('items', {})
        summary = parsed.get('summary', '')
        if summary:
            results['_market_summary'] = summary
        
        if results:
            write_json(os.path.join(DATA_DIR, 'ai_analysis.json'), results)
            print(f'[AI] ✅ {len(results)} items analyzed (1 API call)')
            if summary:
                print(f'[AI] 📊 {summary[:60]}')
    except Exception as e:
        print(f'[AI] ❌ Batch failed: {e}, falling back to individual...')
        # Fallback: 逐件分析
        results = {}
        for i, item in enumerate(items):  # 全部持仓
            name = item.get('name', '')
            cost = item.get('cost', 0); price = item.get('price', 0)
            r7 = item.get('rate_7', 0); r30 = item.get('rate_30', 0)
            pnl_pct = (price - cost) / cost * 100 if cost > 0 else 0
            try:
                data = json.dumps({
                    'model': 'glm-4.7-flash',
                    'messages': [
                        {'role': 'system', 'content': '你是CS2饰品分析师。返回JSON：{"verdict":"持有/买入/减仓/观望","confidence":80,"reason":"一句话","risk":"一句话"}'},
                        {'role': 'user', 'content': f'{name}，¥{price:.0f}，7日{r7:+.1f}%，30日{r30:+.1f}%，成本¥{cost:.0f}，盈亏{pnl_pct:+.1f}%'}
                    ],
                    'response_format': {'type': 'json_object'},
            'thinking': {'type': 'enabled'},
                    'max_tokens': 200, 'temperature': 0.3
                }).encode('utf-8')
                req = urllib.request.Request('https://open.bigmodel.cn/api/paas/v4/chat/completions', data=data, headers={
                    'Authorization': f'Bearer {ZHIPU_KEY}', 'Content-Type': 'application/json'
                })
                resp = urllib.request.urlopen(req, timeout=20)
                rr = json.loads(resp.read().decode('utf-8'))
                item_result = json.loads(rr['choices'][0]['message']['content'])
                # 转为文本兼容旧格式
                v = item_result.get('verdict',''); c = item_result.get('confidence',0)
                rsn = item_result.get('reason',''); risk = item_result.get('risk','')
                results[name] = f'🎯 操作建议: {v}\n置信度: {c}\n📊 核心逻辑: {rsn}\n⚠️ 风险: {risk}'
                print(f'[AI] {i+1}/5 ✅ {name[:30]}')
            except Exception as e2:
                print(f'[AI] ❌ {name[:30]}: {e2}')
        if results:
            write_json(os.path.join(DATA_DIR, 'ai_analysis.json'), results)
            print(f'[AI] Saved {len(results)} (fallback mode)')

def generate_ai_daily_report():
    """AI 自动生成每日市场报告"""
    if not ZHIPU_KEY: return
    try:
        # 收集市场数据作为上下文
        scan = read_json(os.path.join(DATA_DIR, 'market_scan.json'))
        total_items = scan.get('total', 0); avg_p = scan.get('avg_p', 0)
        gainers = scan.get('movers', {}).get('gainers', [])[:5]
        losers = scan.get('movers', {}).get('losers', [])[:5]
        gainer_text = ' | '.join([g.get('n','')[:20] + (' +' + str(g.get('r7','')) + '%' if g.get('r7') else '') for g in gainers])
        loser_text = ' | '.join([l.get('n','')[:20] + (' ' + str(l.get('r7','')) + '%' if l.get('r7') else '') for l in losers])
        prompt = f'CS2饰品市场日报。全市场{total_items}件追踪品，均价¥{avg_p:.0f}。涨幅TOP: {gainer_text}。跌幅TOP: {loser_text}。请用中文写一段150字市场总结。'
        data = json.dumps({
            'model': 'glm-4.7-flash',
            'messages': [
                {'role': 'system', 'content': '你是CS2饰品市场日报编辑。写简洁专业的市场分析。'},
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': 500, 'temperature': 0.5
        }).encode('utf-8')
        req = urllib.request.Request('https://open.bigmodel.cn/api/paas/v4/chat/completions', data=data, headers={
            'Authorization': f'Bearer {ZHIPU_KEY}', 'Content-Type': 'application/json'
        })
        resp = urllib.request.urlopen(req, timeout=30)
        r = json.loads(resp.read().decode('utf-8'))
        report = r['choices'][0]['message']['content']
        write_json(os.path.join(DATA_DIR, 'ai_daily_report.json'), {
            'date': time.strftime('%Y-%m-%d'),
            'report': report,
            'generated': time.strftime('%Y-%m-%d %H:%M:%S')
        })
        print(f'[AI] Daily report generated ({len(report)} chars)')
    except Exception as e:
        print(f'[AI] Daily report failed: {e}')

def generate_ai_anomaly():
    """AI 解读异动饰品"""
    if not ZHIPU_KEY: return
    try:
        # 检查 fluctuation 数据
        bh = read_json(os.path.join(DATA_DIR, 'buff_history.json'))
        dates = sorted(bh.keys())
        if len(dates) < 2: return
        now, prev = dates[-1], dates[-2]
        changes = []
        for name, info in bh[now].items():
            if name not in bh[prev]: continue
            now_num = info.get('buff_sell_num', 0) or info.get('yyyp_sell_num', 0)
            prev_num = bh[prev][name].get('buff_sell_num', 0) or bh[prev][name].get('yyyp_sell_num', 0)
            if prev_num > 0 and now_num > 0:
                pct = (now_num - prev_num) / prev_num * 100
                if abs(pct) > 30:
                    changes.append((name, pct, now_num, prev_num))
        if not changes:
            print('[AI] No significant anomalies')
            return
        changes.sort(key=lambda x: abs(x[1]), reverse=True)
        top = changes[:5]
        items_text = '\n'.join([f'{n}: 在售量 {pr}→{nr} ({pct:+.0f}%)' for n, pct, nr, pr in top])
        prompt = f'CS2饰品在售量异动检测，以下饰品在售量变化超过30%：\n{items_text}\n请分析这些异动可能的原因和影响，100字以内。'
        data = json.dumps({
            'model': 'glm-4.7-flash',
            'messages': [
                {'role': 'system', 'content': '你是CS2饰品市场分析师。简洁分析在售量异动原因。'},
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': 300, 'temperature': 0.5
        }).encode('utf-8')
        req = urllib.request.Request('https://open.bigmodel.cn/api/paas/v4/chat/completions', data=data, headers={
            'Authorization': f'Bearer {ZHIPU_KEY}', 'Content-Type': 'application/json'
        })
        resp = urllib.request.urlopen(req, timeout=20)
        r = json.loads(resp.read().decode('utf-8'))
        result = {'anomalies': [{'name': n, 'pct': round(pct, 1)} for n, pct, _, _ in top], 'analysis': r['choices'][0]['message']['content']}
        write_json(os.path.join(DATA_DIR, 'ai_anomaly.json'), result)
        print(f'[AI] Anomaly analysis done ({len(top)} items)')
    except Exception as e:
        print(f'[AI] Anomaly failed: {e}')

def generate_ai_stock_picks():
    """AI 扫描全市场找低估品"""
    if not ZHIPU_KEY: return
    try:
        scan = read_json(os.path.join(DATA_DIR, 'market_scan.json'))
        movers = scan.get('movers', {})
        losers = movers.get('losers', [])[:20]
        # 取跌幅最大但基本面好的
        items_text = '\n'.join([f'{l.get("n","")}: 7日{l.get("r7","")}% | 现价¥{l.get("p","")}' for l in losers if l.get('r7') and l['r7'] < -5])
        if not items_text:
            print('[AI] No candidates for stock picks')
            return
        prompt = f'以下CS2饰品近期跌幅较大，请从中选出3-5个最有反弹潜力的：\n{items_text}\n返回JSON：{{"picks":[{{"name":"","reason":"","target":"+X%","confidence":80}}],"rationale":"一句话"}}'
        data = json.dumps({
            'model': 'glm-4.7-flash',
            'messages': [{'role': 'system', 'content': '你是CS2饰品投资分析师。只返回JSON。'}, {'role': 'user', 'content': prompt}],
            'response_format': {'type': 'json_object'},
            'max_tokens': 1000, 'temperature': 0.5
        }).encode('utf-8')
        req = urllib.request.Request('https://open.bigmodel.cn/api/paas/v4/chat/completions', data=data, headers={
            'Authorization': f'Bearer {ZHIPU_KEY}', 'Content-Type': 'application/json'
        })
        resp = urllib.request.urlopen(req, timeout=30)
        r = json.loads(resp.read().decode('utf-8'))
        picks = json.loads(r['choices'][0]['message']['content'])
        write_json(os.path.join(DATA_DIR, 'ai_stock_picks.json'), picks)
        print(f'[AI] Stock picks: {len(picks.get("picks",[]))} candidates')
    except Exception as e:
        print(f'[AI] Stock picks failed: {e}')

# ═══════════════ PUSH (single atomic commit) ═══════════════
def push_all():
    """Push all dirty files in a single commit — avoids SHA conflicts"""
    dirty_files.discard('price_history.json')  # never push to GitHub
    if not dirty_files:
        print('[INFO] No files changed, skipping push')
        return

    message = f'chore: update {", ".join(sorted(dirty_files))} {time.strftime("%Y-%m-%d %H:%M")}'
    if os.environ.get('GITHUB_ACTIONS') and GH_TOKEN:
        # CI: skip inline push — git_ops.py push step handles everything
        # (GitHub Contents API has 1MB limit + timeouts on large files like price_history.json)
        print(f'[PUSH] Skipping inline push in CI ({len(dirty_files)} dirty files), git_ops.py will handle')
        for filename in sorted(dirty_files):
            print(f'  [DIRTY] {filename}')
        return
    else:
        # Local: single git commit + push
        git_push_locally(sorted(dirty_files), message)

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
    """Push via local git in a single commit (token-based auth, no popup)"""
    git_env = {**os.environ, 'GCM_INTERACTIVE': 'never', 'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': 'echo'}
    # Hide git console window on Windows
    cf = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    for f in files:
        subprocess.run(['git', 'add', '-f', f], check=True, cwd=DATA_DIR, env=git_env, creationflags=cf)
    subprocess.run(['git', 'commit', '-m', message], check=True, cwd=DATA_DIR, env=git_env, creationflags=cf)
    # 用 Token 认证（如果是本地运行），否则 fallback 到 credential manager
    if GH_TOKEN:
        push_cmd = ['git', '-c', f'http.extraHeader=Authorization: Bearer {GH_TOKEN}',
                    '-c', 'http.sslBackend=openssl', '-c', 'http.sslVerify=false', 'push', 'origin', 'main']
    else:
        push_cmd = ['git', '-c', 'credential.helper=manager',
                    '-c', 'http.sslBackend=openssl', '-c', 'http.sslVerify=false', 'push']
    subprocess.run(push_cmd, check=True, cwd=DATA_DIR, env=git_env, creationflags=cf)
    print(f'[OK] Git pushed: {message}')

# ═══════════════ MAIN ═══════════════
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'

    # ── 静默同步 Git（无窗口弹窗）──
    git_env = {**os.environ, 'GCM_INTERACTIVE': 'never', 'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': 'echo'}
    cf = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
    try:
        subprocess.run(['git', 'stash'], check=False, cwd=DATA_DIR, env=git_env, creationflags=cf, capture_output=True)
        subprocess.run(['git', '-c', 'credential.helper=', 'pull', '--rebase', 'origin', 'main'], check=True, cwd=DATA_DIR, env=git_env, creationflags=cf, capture_output=True)
    except Exception as e:
        print(f'[WARN] Git sync failed: {e}', file=sys.stderr)

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

    # ── Update SteamDT BUFF prices → merge into holdings.json ──
    buff_prices = {}
    if mode in ('all', 'prices') and STEAM_KEY:
        print('[SteamDT] Fetching BUFF prices...')
        try:
            buff_prices = fetch_steamdt_prices(hash_names)
            if buff_prices:
                # Merge BUFF prices into holdings items
                for item in items:
                    hn = item.get('market_hash')
                    if hn and hn in buff_prices:
                        bp = buff_prices[hn]
                        item['buff_sell'] = bp.get('buff_sell', 0)
                        item['buff_buy'] = bp.get('buff_buy', 0)
                        item['buff_sell_num'] = bp.get('buff_sell_num', 0)
                        item['buff_buy_num'] = bp.get('buff_buy_num', 0)
                write_json(holdings_path, holdings)
                print(f'[SteamDT] Merged BUFF prices for {len(buff_prices)} items into holdings')

            # ── 同时合并多平台价格到 eco_tracked.json ──
            eco_path = os.path.join(DATA_DIR, 'eco_tracked.json')
            eco_items = read_json(eco_path)
            if isinstance(eco_items, list) and eco_items:
                merged = 0
                for item in eco_items:
                    hn = item.get('HashName', '')
                    if hn and hn in buff_prices:
                        bp = buff_prices[hn]
                        item['buff_sell'] = bp.get('buff_sell', 0)
                        item['buff_buy'] = bp.get('buff_buy', 0)
                        item['buff_sell_num'] = bp.get('buff_sell_num', 0)
                        item['buff_buy_num'] = bp.get('buff_buy_num', 0)
                        item['buff_source'] = bp.get('buff_source', '')
                        item['platforms'] = bp.get('platforms', {})
                        merged += 1
                write_json(eco_path, eco_items)
                print(f'[SteamDT] Merged multi-platform prices for {merged}/{len(eco_items)} items into eco_tracked.json')
        except Exception as e:
            print(f'[SteamDT] BUFF prices failed: {e}', file=sys.stderr)

    # ── Compute self-alerts from BUFF price history → market.json ──
    alerts_data = []
    if mode in ('all', 'alerts'):
        print('[ALERTS] Computing from BUFF price history...')
        try:
            if buff_prices:
                alerts_data = compute_alerts(buff_prices)
            if alerts_data:
                print(f'[ALERTS] Got {len(alerts_data)} alerts')
                market_path = os.path.join(DATA_DIR, 'market.json')
                market = read_json(market_path)
                market['alerts'] = alerts_data
                market['alerts_updated'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                write_json(market_path, market)
            else:
                print('[ALERTS] No history data yet, skipping alerts')
        except Exception as e:
            print(f'[ALERTS] Failed: {e}', file=sys.stderr)

    # ── Update SteamDT K-lines (optional) ──
    if mode in ('all', 'klines') and STEAM_KEY:
        print('[SteamDT] Fetching K-lines...')
        try:
            market_path = os.path.join(DATA_DIR, 'market.json')
            market = read_json(market_path)
            # 从 holdings.json 读取物品列表（market.json 的 items 可能为空对象）
            holdings_path = os.path.join(DATA_DIR, 'holdings.json')
            holdings = read_json(holdings_path)
            items_list = holdings.get('items', [])
            print(f'[SteamDT] Items list: {len(items_list)} items (from holdings.json)')
            kline_data = fetch_steamdt_klines(items_list)
            print(f'[SteamDT] K-line data: {len(kline_data)} items fetched')
            if kline_data:
                for item in items_list:
                    name = item.get('name_en') or item.get('name', '')
                    if name in kline_data:
                        item['kline'] = kline_data[name]
                market['items'] = items_list
                write_json(market_path, market)
        except Exception as e:
            print(f'[SteamDT] K-lines failed: {e}', file=sys.stderr)


    # ── Update Steam News → news.json ──
    if mode in ('all',):
        print('[NEWS] Fetching CS2 Steam news...')
        try:
            news_data = fetch_steam_news()
            if news_data:
                news_path = os.path.join(DATA_DIR, 'news.json')
                write_json(news_path, news_data)
        except Exception as e:
            print(f'[NEWS] Failed: {e}', file=sys.stderr)

    # ── ECO Catalog (full item data, excludes knives/statrak) ──
    # Start catalog build in background early so it runs in parallel with other steps
    _catalog_future = None
    if mode in ('all', 'eco'):
        print('[ECO] Building catalog (parallel background)...')
        try:
            # 备份带BUFF数据的旧文件，防止CSQAQ失败后丢失平台数据
            tracked_path_bak = os.path.join(DATA_DIR, 'eco_tracked.json')
            if os.path.exists(tracked_path_bak):
                shutil.copy2(tracked_path_bak, tracked_path_bak + '.bak')
            _catalog_executor = ThreadPoolExecutor(max_workers=1)
            _catalog_future = _catalog_executor.submit(eco_catalog.build)
        except Exception as e:
            print(f'[ECO] Failed to start catalog: {e}', file=sys.stderr)

    # ── Generate Recommendations (dual ECO/BUFF scoring from catalog) ──
    if mode in ('all', 'alerts'):
        # Wait for catalog build to finish before generating recommendations
        if _catalog_future is not None:
            print('[REC] Waiting for catalog build...')
            try:
                _catalog_future.result()
                print('[REC] Catalog ready, generating recommendations')
            except Exception as e:
                print(f'[REC] Catalog failed: {e}', file=sys.stderr)

        # ── CSQAQ + SteamDT 综合多平台数据 ──
        # 目标：让全量饰品都有价格数据
        try:
            tracked_path = os.path.join(DATA_DIR, 'eco_tracked.json')
            tracked = read_json(tracked_path) if os.path.exists(tracked_path) else []
            if not isinstance(tracked, list):
                tracked = []

            if tracked:
                # 1. CSQAQ 排行榜（200件，最快，含涨跌率）
                csqaq_alerts = recommend.fetch_csqaq_alerts()
                if csqaq_alerts:
                    csqaq_map = {}
                    for a in csqaq_alerts:
                        csqaq_map[a['name']] = a
                    merged = 0
                    for item in tracked:
                        hn = item.get('HashName', '')
                        if hn and hn in csqaq_map:
                            ca = csqaq_map[hn]
                            if ca.get('price', 0) > 0:
                                item['buff_sell'] = ca['price']
                                item['buff_source'] = 'BUFF'
                            item['buff_buy'] = ca.get('buff_buy_price', 0) or item.get('buff_buy', 0)
                            item['buff_sell_num'] = ca.get('buff_sell', 0) or item.get('buff_sell_num', 0)
                            item['buff_buy_num'] = ca.get('buff_buy', 0) or item.get('buff_buy_num', 0)
                            merged += 1
                    print(f'[CSQAQ] Rank list merged: {merged} items')

                # 2. CSQAQ 全量查价（每次更新重新扫描所有饰品，保证数据最新）
                all_hashnames = [it['HashName'] for it in tracked if it.get('HashName')]
                if all_hashnames:
                    print(f'[CSQAQ] Full scan: {len(all_hashnames)} items...')
                    batch_prices = recommend.fetch_csqaq_batch_prices(all_hashnames)
                    if batch_prices:
                        merged = 0
                        for item in tracked:
                            hn = item.get('HashName', '')
                            if hn and hn in batch_prices:
                                bp = batch_prices[hn]
                                if bp.get('buff_sell', 0) > 0:
                                    item['buff_sell'] = bp['buff_sell']
                                    item['buff_source'] = 'BUFF'
                                item['buff_sell_num'] = bp.get('buff_sell_num', 0) or item.get('buff_sell_num', 0)
                                item['yyyp_sell'] = bp.get('yyyp_sell', 0)
                                item['yyyp_sell_num'] = bp.get('yyyp_sell_num', 0)
                                merged += 1
                        print(f'[CSQAQ] Batch merged: {merged} items')
                        # ── CSQAQ 全量数据 → 保存到 buff_history（秒级完成，无批次限制）──
                        if batch_prices and len(batch_prices) > 100:
                            try:
                                save_buff_history(batch_prices)
                                print(f'[HISTORY] Saved {len(batch_prices)} items from CSQAQ to buff_history.json')
                            except Exception as e:
                                print(f'[HISTORY] CSQAQ save failed: {e}', file=sys.stderr)

                # 自动检测：BUFF/YYYP 覆盖率过低时保留旧数据
                if merged > 0 and merged < len(tracked) * 0.5:
                    print(f'[CSQAQ] ⚠️ 覆盖率仅 {merged/len(tracked)*100:.0f}%（<50%），尝试恢复备份！')
                    # 尝试从备份恢复（.bak 是build前备份的带BUFF数据的老文件）
                    bak_path = tracked_path + '.bak'
                    if os.path.exists(bak_path):
                        tracked_old = read_json(bak_path)
                        if tracked_old:
                            old_buff = sum(1 for it in tracked_old if (it.get('buff_sell', 0) or 0) > 0)
                            if old_buff > merged:
                                print(f'[CSQAQ] 恢复备份：{old_buff} 件BUFF价格 > 新数据 {merged} 件')
                                tracked = tracked_old
                            else:
                                write_json(tracked_path, tracked)
                        else:
                            write_json(tracked_path, tracked)
                    else:
                        write_json(tracked_path, tracked)
                else:
                    write_json(tracked_path, tracked)
                # 清理备份文件
                bak_path = tracked_path + '.bak'
                if os.path.exists(bak_path):
                    os.remove(bak_path)

            # 3. SteamDT 补充（持仓32件 + 部分全量）
            if STEAM_KEY:
                try:
                    holdings_path = os.path.join(DATA_DIR, 'holdings.json')
                    holdings = read_json(holdings_path)
                    h_items = holdings.get('items', [])
                    hn_list = [it['market_hash'] for it in h_items if it.get('market_hash')]
                    if hn_list:
                        print(f'[SteamDT] Updating {len(hn_list)} holdings...')
                        sp = fetch_steamdt_prices(hn_list, verbose=False)
                        if sp:
                            for item in h_items:
                                hn = item.get('market_hash', '')
                                if hn in sp:
                                    bp = sp[hn]
                                    item['buff_sell'] = bp.get('buff_sell', 0)
                                    item['buff_buy'] = bp.get('buff_buy', 0)
                                    item['buff_sell_num'] = bp.get('buff_sell_num', 0)
                                    item['buff_buy_num'] = bp.get('buff_buy_num', 0)
                            write_json(holdings_path, holdings)
                            print(f'[SteamDT] Holdings updated: {len(sp)} items')
                except Exception as e:
                    print(f'[SteamDT] Holdings update failed: {e}', file=sys.stderr)
        except Exception as e:
            print(f'[MultiPrice] Failed: {e}', file=sys.stderr)

        # ── 用全量追踪数据获取多平台价格（SteamDT）──
        # 之前 prices 分支只查了持仓的 32 件，现在 eco_tracked.json 已建好
        # 拿全量 hash_names 去查，让 5000+ 件都有 BUFF/悠悠/C5/IGXE 价格
        try:
            tracked_path = os.path.join(DATA_DIR, 'eco_tracked.json')
            if os.path.exists(tracked_path) and STEAM_KEY:
                tracked = read_json(tracked_path)
                if isinstance(tracked, list) and len(tracked) > len(buff_prices):
                    all_hn = [it['HashName'] for it in tracked if it.get('HashName')]
                    print(f'[SteamDT] Fetching multi-platform prices for {len(all_hn)} tracked items...')
                    full_prices = fetch_steamdt_prices(all_hn, verbose=False)
                    if full_prices and len(full_prices) > len(buff_prices):
                        buff_prices = full_prices  # 用全量数据替换
                        # 合并到 eco_tracked.json
                        merged = 0
                        for item in tracked:
                            hn = item.get('HashName', '')
                            if hn and hn in full_prices:
                                bp = full_prices[hn]
                                item['buff_sell'] = bp.get('buff_sell', 0)
                                item['buff_buy'] = bp.get('buff_buy', 0)
                                item['buff_sell_num'] = bp.get('buff_sell_num', 0)
                                item['buff_buy_num'] = bp.get('buff_buy_num', 0)
                                item['platforms'] = bp.get('platforms', {})
                                merged += 1
                        write_json(tracked_path, tracked)
                        print(f'[SteamDT] Merged {merged}/{len(tracked)} items (full catalog + platforms)')
                        
                        # ── 用全量数据保存 BUFF 历史快照 ──
                        if buff_prices and len(buff_prices) > 0:
                            try:
                                save_buff_history(buff_prices)
                                print(f'[HISTORY] Saved {len(buff_prices)} items to buff_history.json')
                            except Exception as e:
                                print(f'[HISTORY] Save failed: {e}', file=sys.stderr)
        except Exception as e:
            print(f'[SteamDT] Full-catalog fetch failed: {e}', file=sys.stderr)
        try:
            recs = generate_recommendations(alerts=alerts_data, steamdt_prices=buff_prices)
            total = len(recs.get('all', []))
            eco_n = sum(1 for r in recs.get('all', []) if r.get('tag') == 'eco')
            buff_n = sum(1 for r in recs.get('all', []) if r.get('tag') == 'buff')
            print(f'[REC] {total} recommendations (ECO={eco_n}, BUFF={buff_n})')

            market_path = os.path.join(DATA_DIR, 'market.json')
            market = read_json(market_path)
            market['recommendations'] = recs
            write_json(market_path, market)

            # ── Record price history for ALL tracked items ──
            try:
                tracked_path = os.path.join(DATA_DIR, 'eco_tracked.json')
                if os.path.exists(tracked_path):
                    tracked = read_json(tracked_path)
                    hist_path = os.path.join(DATA_DIR, 'price_history.json')
                    try:
                        price_hist = read_json(hist_path)
                    except (FileNotFoundError, json.JSONDecodeError):
                        price_hist = {}
                    now = time.strftime('%Y-%m-%dT%H:%M', time.gmtime())
                    recorded = 0
                    for it in tracked:
                        hn = it.get('HashName', '')
                        if not hn:
                            continue
                        # 跳过没有平台数据的物品（只有ECO底价不进history）
                        multi_p = float(it.get('buff_sell', 0) or 0)
                        yyyp_p = float(it.get('yyyp_sell', 0) or 0)
                        if multi_p <= 0 and yyyp_p <= 0:
                            continue
                        if hn not in price_hist:
                            price_hist[hn] = {'eco': [], 'multi': [], 'yyyp': []}
                        else:
                            # 迁移旧条目（可能缺少某些通道）
                            for ch in ('eco', 'multi', 'yyyp'):
                                if ch not in price_hist[hn]:
                                    price_hist[hn][ch] = []
                        eco_p = float(it.get('Price', 0) or 0)
                        if eco_p > 0:
                            price_hist[hn]['eco'].append({'t': now, 'p': eco_p})
                            recorded += 1
                        if multi_p > 0:
                            price_hist[hn]['multi'].append({'t': now, 'p': multi_p})
                        if yyyp_p > 0:
                            price_hist[hn]['yyyp'].append({'t': now, 'p': yyyp_p})
                    # 修剪历史数据（每个通道最多保留500点，约3.5天）
                    MAX_HIST = 500
                    for hn in price_hist:
                        for ch in ('eco', 'multi', 'yyyp'):
                            pts = price_hist[hn].get(ch, [])
                            if len(pts) > MAX_HIST:
                                price_hist[hn][ch] = pts[-MAX_HIST:]
                    write_json(hist_path, price_hist)
                    # Inject price history into rec items
                    for r in recs.get('all', []):
                        hn = r.get('hash_name', '')
                        if hn in price_hist:
                            r['eco_history'] = [e['p'] for e in price_hist[hn].get('eco', [])]
                            r['multi_history'] = [e['p'] for e in price_hist[hn].get('multi', [])]
                            r['yyyp_history'] = [e['p'] for e in price_hist[hn].get('yyyp', [])]
                    # Re-write market.json with history injected
                    market['recommendations'] = recs
                    # Include tracked item names for frontend autocomplete
                    name_set = set()
                    for it in tracked:
                        hn = it.get('HashName', '') or ''
                        gn = it.get('GoodsName', '') or ''
                        if hn: name_set.add(hn)
                        if gn: name_set.add(gn)
                    market['eco_tracked_names'] = sorted(name_set)[:3000]  # 前端只用到前3000
                    write_json(market_path, market)
                    print(f'[PRICE_HIST] Recorded ECO prices for {recorded}/{len(tracked)} items')
            except Exception as e:
                print(f'[PRICE_HIST] Failed: {e}', file=sys.stderr)
        except Exception as e:
            print(f'[REC] Failed: {e}', file=sys.stderr)

    # ── Steam Market full item list + recommendations (replaces ECO) ──
    if mode in ('all', 'market'):
        if _check_host_blocked('steamcommunity.com'):
            print('[MARKET] Skipped (steamcommunity.com blocked by hosts file)')
        else:
            print('[MARKET] Fetching Steam Market items...')
            try:
                items = sm.fetch_steam_market_items(max_items=200, min_price=5.0, max_pages=15)
                
                # Fetch BUFF prices via SteamDT for market items
                if STEAM_KEY:
                    market_hash_names = [it['name_en'] for it in items if it.get('name_en')]
                    if market_hash_names:
                        print(f'[MARKET] Fetching BUFF prices for {len(market_hash_names)} items (SteamDT)...')
                        smdt_prices = fetch_steamdt_prices(market_hash_names)
                        if smdt_prices:
                            for it in items:
                                hn = it.get('name_en', '')
                                if hn in smdt_prices:
                                    bp = smdt_prices[hn]
                                    it['buff_sell'] = bp.get('buff_sell', 0)
                                    it['buff_buy'] = bp.get('buff_buy', 0)
                                    it['buff_sell_num'] = bp.get('buff_sell_num', 0)
                                    it['buff_buy_num'] = bp.get('buff_buy_num', 0)
                            print(f'[MARKET] Merged BUFF prices for {len(smdt_prices)} items')
                
                hp = os.path.join(DATA_DIR, 'market_history.json')
                history = sm.update_market_history(items, hp)
                alerts = sm.compute_alerts_from_history(history)
                recs = sm.generate_recommendations(alerts, items)

                # Write to market.json
                market_path = os.path.join(DATA_DIR, 'market.json')
                market = read_json(market_path)
                market['steam_market_items'] = len(items)
                # Don't overwrite REC's dual-channel recommendations
                if 'recommendations' not in market:
                    market['recommendations'] = recs
                market['steam_market_recs'] = recs
                market['market_updated'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                write_json(market_path, market)
                print(f'[MARKET] Done: {len(items)} items, saved to market.json')
            except Exception as e:
                print(f'[MARKET] Failed: {e}', file=sys.stderr)

    # ── 同步生成全市场扫描快照 ──
    try:
        import generate_scan
        generate_scan.main()
        dirty_files.add('market_scan.json')
        print('[SCAN] market_scan.json regenerated')
    except Exception as e:
        print(f'[SCAN] generate_scan failed: {e}', file=sys.stderr)

    # ── 同步生成关联分析数据 ──
    try:
        import generate_correlation
        generate_correlation.main()
        dirty_files.add('correlation_data.json')
    except Exception as e:
        print(f'[CORR] generate_correlation failed: {e}', file=sys.stderr)

    # ── 生成完整中文名映射（所有物品）──
    try:
        import_namejs = lambda d: os.path.join(d)
        eco_cat_path = os.path.join(DATA_DIR, 'eco_catalog.json')
        name_map_path = os.path.join(DATA_DIR, 'name_map.json')
        catalog = json.load(open(eco_cat_path, 'r', encoding='utf-8'))
        name_map = {}
        for x in catalog:
            if x.get('HashName') and x.get('GoodsName'):
                name_map[x['HashName']] = x['GoodsName']
        json.dump(name_map, open(name_map_path, 'w', encoding='utf-8'), ensure_ascii=False)
        dirty_files.add('name_map.json')
        print(f'[NAME] Generated name_map.json: {len(name_map)} items')
    except Exception as e:
        print(f'[NAME] name_map generation skipped: {e}', file=sys.stderr)

    # ── 同步生成日报（每天一次）──
    try:
        report_path = os.path.join(DATA_DIR, 'daily_report.json')
        need_regenerate = True
        if os.path.exists(report_path):
            try:
                old = json.load(open(report_path, encoding='utf-8'))
                if old.get('date') == time.strftime('%Y-%m-%d'):
                    need_regenerate = False
            except: pass
        if need_regenerate:
            import generate_report
            generate_report.main()
            dirty_files.add('daily_report.json')
    except Exception as e:
        print(f'[REPORT] generate_report failed: {e}', file=sys.stderr)

    # ── 同步生成数据状态摘要 ──
    try:
        import json
        status_summary = {'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        # price_history dates
        ph_path = os.path.join(DATA_DIR, 'price_history.json')
        if os.path.exists(ph_path):
            ph = json.load(open(ph_path, encoding='utf-8'))
            all_d = set()
            for item, sources in ph.items():
                if isinstance(sources, dict):
                    for dp in sources.get('eco', [])[:5]:
                        d = dp.get('t', '')[:10]
                        if d: all_d.add(d)
                if len(all_d) >= 3: break
            status_summary['price_dates'] = sorted(all_d)[:50]
        # buff_history dates
        bh_path = os.path.join(DATA_DIR, 'buff_history.json')
        if os.path.exists(bh_path):
            bh = json.load(open(bh_path, encoding='utf-8'))
            b_dates = sorted(bh.keys())
            status_summary['buff_history'] = {
                'count': len(b_dates),
                'first': b_dates[0] if b_dates else '',
                'last': b_dates[-1] if b_dates else '',
            }
        # file sizes/timestamps
        for fn in ['eco_tracked.json','holdings.json','market.json','price_history.json']:
            fp = os.path.join(DATA_DIR, fn)
            if os.path.exists(fp):
                st = os.stat(fp)
                status_summary[fn] = {'size': st.st_size, 'mtime': time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))}
        out = os.path.join(DATA_DIR, 'data_status.json')
        json.dump(status_summary, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
        dirty_files.add('data_status.json')
        print(f'[STATUS] Summary generated: {len(status_summary)} fields')
    except Exception as e:
        print(f'[STATUS] Summary failed: {e}', file=sys.stderr)

    # ── 更新时间戳 ──
    market_path = os.path.join(DATA_DIR, 'market.json')
    if os.path.exists(market_path):
        try:
            m = read_json(market_path)
            if m: m['updated'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()); write_json(market_path, m)
        except: pass

    # ── 衍生 price_summary + AI 分析 ──
    generate_price_summary()
    try: generate_ai_analysis()
    except Exception as e: print(f'[AI] Analysis failed (non-fatal): {e}', file=sys.stderr)
    try: generate_ai_daily_report()
    except Exception as e: print(f'[AI] Daily report failed (non-fatal): {e}', file=sys.stderr)
    try: generate_ai_anomaly()
    except Exception as e: print(f'[AI] Anomaly detection failed (non-fatal): {e}', file=sys.stderr)
    try: generate_ai_stock_picks()
    except Exception as e: print(f'[AI] Stock picks failed (non-fatal): {e}', file=sys.stderr)

    # ── Push all dirty files at once ──
    push_all()

    print('=== Done ===')

if __name__ == '__main__':
    main()
