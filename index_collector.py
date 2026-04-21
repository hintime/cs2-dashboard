#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CS2 大盘指数收集器 v3.5（稳定版）

今日指数 = 1000 × Σ(当前价格 × 初始在售数) / Σ(初始价格 × 初始在售数)
"""
import json, time, base64, urllib.request, os, sys, ssl
from datetime import datetime, timedelta
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256

# ════════════════════ CONFIG ════════════════════
PARTNER_ID = 'da740aa96cc14cc594371f95469c90ac'
ECO_BASE = 'https://openapi.ecosteam.cn'

# 选品规则常量
MIN_PRICE = 1.0
STICKER_MIN_SELLING = 101
PRICE_THRESHOLDS = ((1, 5, 800), (5, 10, 300), (10, 100, 80), (100, 1000, 50), (1000, float('inf'), 30))

# 路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, '..') if SCRIPT_DIR.endswith('.github') else SCRIPT_DIR
HIST_DIR = os.path.join(DATA_DIR, 'market_history')
INDEX_DIR = os.path.join(DATA_DIR, 'index_history')

# SSL
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# ════════════════════ ECO API ════════════════════
_eco_key = None

def get_eco_key():
    global _eco_key
    if _eco_key:
        return _eco_key
    key_b64 = os.environ.get('ECO_PRIVATE_KEY_B64', '')
    if key_b64:
        try:
            _eco_key = RSA.import_key(base64.b64decode(key_b64))
            return _eco_key
        except Exception as e:
            print(f'[WARN] ECO key decode failed: {e}')
    for path in ('eco_private.pem', '../eco_private.pem', '../../eco_private_key.pem'):
        full = os.path.join(SCRIPT_DIR, path)
        if os.path.exists(full):
            try:
                with open(full, 'rb') as f:
                    _eco_key = RSA.import_key(f.read())
                print(f'[INFO] Loaded key from {full}')
                return _eco_key
            except:
                pass
    return None

def sign_eco(params, key):
    parts = []
    for k, v in sorted(params.items(), key=lambda x: x[0].lower()):
        if v is None or v == '':
            continue
        if isinstance(v, (list, dict)):
            v = json.dumps(v, separators=(',', ':'), ensure_ascii=False)
        parts.append(f'{k}={v}')
    sig = pkcs1_15.new(key).sign(SHA256.new('&'.join(parts).encode('utf-8')))
    return base64.b64encode(sig).decode()

def fetch_eco(retries=3):
    """获取ECO数据（带重试）"""
    for attempt in range(retries):
        key = get_eco_key()
        if not key:
            print('[ERROR] ECO key not found')
            return None
        
        ts = str(int(time.time()))
        params = {'PartnerId': PARTNER_ID, 'Timestamp': ts, 'GameID': '730'}
        params['Sign'] = sign_eco(params, key)
        
        try:
            req = urllib.request.Request(
                f'{ECO_BASE}/Api/Market/GetHashNameAndPriceList',
                data=json.dumps(params).encode(),
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
                items = json.loads(r.read().decode('utf-8')).get('ResultData', [])
                print(f'[ECO] Got {len(items)} items')
                return items
        except Exception as e:
            print(f'[ECO] Attempt {attempt+1} failed: {e}')
            if attempt < retries - 1:
                time.sleep(2)
    return None

# ════════════════════ 选品筛选 ════════════════════

def filter_items(items):
    """按规则筛选饰品"""
    filtered = []
    ex_p = ex_t = ex_s = 0
    
    for item in items:
        name = item.get('HashName', '')
        price = float(item.get('Price') or item.get('MarketComprePrice') or 0)
        selling = int(item.get('SellingTotal') or 0)
        
        if price < MIN_PRICE:
            ex_p += 1
            continue
        if 'StatTrak' in name or 'Souvenir' in name:
            ex_t += 1
            continue
        
        is_sticker = name.startswith('Sticker |')
        if is_sticker:
            if selling <= STICKER_MIN_SELLING:
                ex_s += 1
                continue
        else:
            passed = False
            for min_p, max_p, min_s in PRICE_THRESHOLDS:
                if min_p <= price < max_p:
                    passed = selling >= min_s
                    break
            if not passed:
                ex_s += 1
                continue
        
        item['_price'] = price
        filtered.append(item)
    
    print(f'[FILTER] {len(items)} → {len(filtered)} (ex_p={ex_p}, ex_t={ex_t}, ex_s={ex_s})')
    return filtered

# ════════════════════ 指数计算 ════════════════════

def calc_weighted_value(items, weights):
    total = 0.0
    get_weight = weights.get
    for item in items:
        price = item.get('_price')
        if price is None:
            price = float(item.get('Price') or item.get('MarketComprePrice') or 0)
            if price <= 0:
                continue
        name = item.get('HashName', '')
        weight = get_weight(name, int(item.get('SellingTotal') or 0))
        total += price * max(weight, 1)
    return round(total, 2)

def calc_index(current_items, base_data):
    if not base_data:
        weights = {i.get('HashName', ''): int(i.get('SellingTotal') or 0) for i in current_items}
        mv = calc_weighted_value(current_items, weights)
        return {'index': 1000.0, 'change_pct': 0.0, 'current_mv': mv, 'base_mv': mv, 
                'weights': weights, 'total_items': len(current_items)}
    
    weights = base_data.get('weights', {})
    curr_mv = calc_weighted_value(current_items, weights)
    base_mv = base_data.get('base_mv', 1)
    
    if base_mv > 0:
        idx = (curr_mv / base_mv) * 1000
        chg = (curr_mv - base_mv) / base_mv * 100
    else:
        idx, chg = 1000.0, 0.0
    
    return {'index': round(idx, 2), 'change_pct': round(chg, 2), 
            'current_mv': curr_mv, 'base_mv': base_mv, 'weights': weights,
            'total_items': len(current_items)}

# ════════════════════ 统计计算 ════════════════════

def calc_changes(current, prev_items):
    if not prev_items:
        return {'gainers': 0, 'losers': 0, 'unchanged': 0, 'top_gainers': [], 'top_losers': []}
    
    prev_prices = {i.get('HashName'): i.get('Price', 0) for i in prev_items if i.get('HashName')}
    
    changes = []
    gainers = losers = unchanged = 0
    
    for item in current:
        name = item.get('HashName', '')
        price = item.get('_price')
        if price is None:
            price = float(item.get('Price') or item.get('MarketComprePrice') or 0)
        
        prev_price = prev_prices.get(name, 0)
        if prev_price <= 0 or price <= 0:
            continue
        
        chg = (price - prev_price) / prev_price * 100
        changes.append((name[:35], round(price, 2), round(chg, 2)))
        
        if chg > 0.1: gainers += 1
        elif chg < -0.1: losers += 1
        else: unchanged += 1
    
    changes.sort(key=lambda x: x[2], reverse=True)
    return {'gainers': gainers, 'losers': losers, 'unchanged': unchanged,
            'top_gainers': [{'name': n, 'price': p, 'change': c} for n, p, c in changes[:10]],
            'top_losers': [{'name': n, 'price': p, 'change': c} for n, p, c in changes[-10:][::-1]]}

def calc_selling_stats(current, prev):
    curr_s = sum(int(i.get('SellingTotal') or 0) for i in current)
    prev_s = sum(int(i.get('SellingTotal') or 0) for i in prev) if prev else 0
    delta = curr_s - prev_s
    return {'total_selling': curr_s, 'total_selling_prev': prev_s,
            'total_selling_delta': delta,
            'total_selling_delta_pct': round(delta / prev_s * 100, 2) if prev_s else 0}

def calc_trending(current, prev, top_n=15):
    if not prev:
        return {'hot': [], 'cold': []}
    
    prev_map = {i.get('HashName', ''): int(i.get('SellingTotal') or 0) for i in prev}
    changes = []
    
    for item in current:
        name = item.get('HashName', '')
        curr_s = int(item.get('SellingTotal') or 0)
        prev_s = prev_map.get(name, 0)
        if curr_s == prev_s:
            continue
        
        delta = curr_s - prev_s
        price = item.get('_price')
        if price is None:
            price = float(item.get('Price') or item.get('MarketComprePrice') or 0)
        
        changes.append({
            'hash_name': name,
            'goods_name': item.get('GoodsName', name),
            'price': price,
            'current_selling': curr_s, 'prev_selling': prev_s,
            'selling_delta': delta,
            'selling_delta_pct': round(delta / prev_s * 100, 1) if prev_s else (999 if delta > 0 else -999)
        })
    
    changes.sort(key=lambda x: x['selling_delta'], reverse=True)
    return {'hot': changes[:top_n], 'cold': changes[-top_n:][::-1]}

# ════════════════════ 存储 ════════════════════

def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return default

def save_json(path, data, indent=None):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)

def load_prev_items(date_str):
    now = datetime.now()
    prev = now - timedelta(hours=1)
    prev_date = prev.strftime('%Y-%m-%d') if now.hour == 0 else date_str
    path = os.path.join(HIST_DIR, f'{prev_date}_{prev.strftime("%H")}00.json')
    return load_json(path, {}).get('items')

def save_snapshot(date_str, hour, items, index_info, changes, selling, trending):
    mini_items = [{'HashName': i.get('HashName'), 
                   'Price': i.get('_price') or float(i.get('Price') or i.get('MarketComprePrice') or 0), 
                   'SellingTotal': int(i.get('SellingTotal') or 0)} for i in items]
    
    path = os.path.join(HIST_DIR, f'{date_str}_{hour}00.json')
    save_json(path, {
        'time': f'{hour}:00', 'timestamp': int(time.time()),
        'items': mini_items,
        'index': index_info['index'], 'change_pct': index_info['change_pct'],
        'total_market_value': index_info['current_mv'],
        'change_stats': changes, 'selling_stats': selling, 'trending': trending
    })
    print(f'[SAVE] {path}')
    return path

def ensure_base(items, index_info):
    path = os.path.join(HIST_DIR, 'base.json')
    if os.path.exists(path):
        return load_json(path)
    
    weights = {i.get('HashName', ''): int(i.get('SellingTotal') or 0) for i in items}
    data = {
        'base_date': datetime.now().strftime('%Y-%m-%d'),
        'weights': weights,
        'base_mv': index_info['current_mv'],
        'total_items': len(items)
    }
    save_json(path, data, indent=2)
    print(f'[BASE] Created with {len(weights)} weights')
    return data

def update_series(date_str, index_info, reset=False):
    path = os.path.join(INDEX_DIR, f'{date_str}.json')
    data = {'date': date_str, 'series': []} if reset else load_json(path, {'date': date_str, 'series': []})
    
    data['series'].append({
        'time': datetime.now().strftime('%H:%M'),
        'timestamp': int(time.time()),
        'index': index_info['index'],
        'change_pct': index_info['change_pct'],
        'market_value': index_info['current_mv']
    })
    
    if len(data['series']) > 48:
        data['series'] = data['series'][-48:]
    
    save_json(path, data)
    print(f'[SERIES] {len(data["series"])} points')
    return data['series']

def sync_market(date_str, index_info, series, selling, trending):
    """同步到 market.json（合并历史K线）"""
    path = os.path.join(DATA_DIR, 'market.json')
    market = load_json(path, {})
    
    # 合并所有历史series数据
    all_series = []
    if os.path.exists(INDEX_DIR):
        for f in os.listdir(INDEX_DIR):
            if f.endswith('.json') and f != f'{date_str}.json':
                hist = load_json(os.path.join(INDEX_DIR, f), {})
                if hist.get('series'):
                    all_series.extend(hist['series'])
    # 添加今天的series
    if series:
        all_series.extend(series)
    
    # 构建K线
    ohlc = []
    vol_bar = []
    
    if all_series and len(all_series) >= 1:
        max_mv = max((s.get('market_value') or 1) for s in all_series)
        
        # 每2小时分组
        for i in range(0, len(all_series), 2):
            group = all_series[i:i+2]
            if not group:
                continue
            
            first, last = group[0], group[-1]
            indices = [s['index'] for s in group]
            
            ohlc.append({
                'date': first.get('time', '00:00').split(':')[0] + ':00',
                'dateFull': f"{first.get('time','00:00')}",
                'open': first['index'],
                'close': last['index'],
                'high': max(indices),
                'low': min(indices)
            })
            vol_bar.append(round(last.get('market_value', 0) / max_mv * 1000))
    
    # 使用合并后的历史数据
    final_series = all_series
    last = final_series[-1] if final_series else {}
    
    market['index'] = {
        'latest': index_info['index'],
        'change': last.get('change_pct', 0),
        'change_pct': last.get('change_pct', 0),
        'market_value': index_info['current_mv'],
        'total_items': index_info['total_items'],
        'updated': datetime.now().strftime('%Y-%m-%dT%H:%M:%S+08:00'),
        'ohlc': ohlc, 'volBar': vol_bar,
        'volColor': ['#f87171' if v > 500 else '#52525b' for v in vol_bar],
        'series': final_series, 'selling': selling or {}, 'trending': trending or {'hot': [], 'cold': []}
    }
    market['index_updated'] = int(time.time() * 1000)
    save_json(path, market)
    print(f'[MKT] {len(ohlc)} candles')
    return path

def cleanup_old_snapshots(days_to_keep=7):
    """清理旧快照"""
    if not os.path.exists(HIST_DIR):
        return
    now = datetime.now()
    cleaned = 0
    for f in os.listdir(HIST_DIR):
        if not f.endswith('.json') or f == 'base.json':
            continue
        try:
            fpath = os.path.join(HIST_DIR, f)
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            if (now - mtime).days > days_to_keep:
                os.remove(fpath)
                cleaned += 1
        except:
            pass
    if cleaned:
        print(f'[CLEAN] Removed {cleaned} old snapshots')

# ════════════════════ MAIN ════════════════════

def main():
    print('=== CS2 Market Index v3.5 ===')
    start_time = time.time()
    
    date_str = datetime.now().strftime('%Y-%m-%d')
    hour = datetime.now().strftime('%H')
    
    # 获取数据
    items = fetch_eco()
    if not items:
        return 1
    
    # 筛选
    filtered = filter_items(items)
    
    # 加载基期
    base = load_json(os.path.join(HIST_DIR, 'base.json'))
    
    # 计算指数
    idx = calc_index(filtered, base)
    print(f'[INDEX] {idx["index"]:.2f} ({idx["change_pct"]:+.2f}%) MV={idx["current_mv"]:,.0f}')
    
    # 上一小时
    prev = load_prev_items(date_str)
    
    # 统计
    changes = calc_changes(filtered, prev)
    selling = calc_selling_stats(filtered, prev)
    trending = calc_trending(filtered, prev)
    print(f'[STATS] selling={selling["total_selling"]:,} Δ{selling["total_selling_delta"]:+,}')
    
    # 保存
    snap = save_snapshot(date_str, hour, filtered, idx, changes, selling, trending)
    
    # 基期
    is_new = False
    if not base:
        base = ensure_base(filtered, idx)
        idx['weights'] = base['weights']
        is_new = True
    
    # 序列和同步
    series = update_series(date_str, idx, reset=is_new)
    market = sync_market(date_str, idx, series, selling, trending)
    
    # 清理旧数据
    cleanup_old_snapshots()
    
    elapsed = time.time() - start_time
    print(f'[DONE] {elapsed:.2f}s')
    return 0

if __name__ == '__main__':
    sys.exit(main())
