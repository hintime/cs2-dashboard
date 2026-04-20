#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CS2 大盘指数收集器 v3.1（优化版）

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
CSQAQ_BASE = 'https://api.csqaq.com'
CSQAQ_TOKEN = os.environ.get('CSQAQ_API_TOKEN') or 'HXGPY1R7L5W7K7F3O4K1E2N8'

# 选品规则常量
MIN_PRICE = 1.0
STICKER_MIN_SELLING = 101
PRICE_THRESHOLDS = [
    (1, 5, 800),      # (min, max, min_selling)
    (5, 10, 500),
    (10, 100, 100),
    (100, 1000, 80),
    (1000, float('inf'), 50),
]

# 路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, '..') if SCRIPT_DIR.endswith('.github') else SCRIPT_DIR
HIST_DIR = os.path.join(DATA_DIR, 'market_history')
INDEX_DIR = os.path.join(DATA_DIR, 'index_history')

# SSL（ECO API 需要）
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# ════════════════════ CSQAQ API (在售量) ════════════════════

def fetch_csqaq_selling():
    """从 CSQAQ 获取所有饰品的在售量数据（BUFF+悠悠）"""
    all_items = {}
    page_size = 500  # 最大分页
    page_index = 1
    max_pages = 20  # 最多20页（10,000件），CSQAQ实际有约10,000+件
    
    headers = {
        'ApiToken': CSQAQ_TOKEN,
        'Content-Type': 'application/json'
    }
    
    print('[CSQAQ] Fetching selling data...')
    
    while page_index <= max_pages:
        body = {
            'page_index': page_index,
            'page_size': page_size,
            'filter': {'type': ['sticker', 'normal']},  # 包含贴纸和普通饰品
            'show_recently_price': False
        }
        
        try:
            req = urllib.request.Request(
                f'{CSQAQ_BASE}/api/v1/info/get_rank_list',
                data=json.dumps(body).encode('utf-8'),
                headers=headers,
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode('utf-8'))
                
                if data.get('code') != 200:
                    print(f'[CSQAQ] API error: {data.get("msg")}')
                    break
                
                items = data.get('data', {}).get('data', [])
                if not items:
                    break
                
                for item in items:
                    # CSQAQ 用 'id' 而不是 'good_id'
                    item_id = item.get('id')
                    if item_id:
                        # 使用 BUFF+悠悠 在售量之和
                        buff_sell = int(item.get('buff_sell_num') or 0)
                        yyyp_sell = int(item.get('yyyp_sell_num') or 0)
                        total_sell = buff_sell + yyyp_sell
                        
                        # name 可能乱码，用 id 作为 key
                        all_items[item_id] = {
                            'name': item.get('name', ''),
                            'buff_sell': buff_sell,
                            'yyyp_sell': yyyp_sell,
                            'total_sell': total_sell,
                            'price': float(item.get('buff_sell_price') or 0)  # 已经是元
                        }
                
                print(f'[CSQAQ] Page {page_index}: got {len(items)} items, total {len(all_items)}')
                
                if len(items) < page_size:
                    break
                page_index += 1
                time.sleep(0.5)  # 延迟500ms，避免429
                
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f'[CSQAQ] Rate limited, waiting 5s...')
                time.sleep(5)
                continue  # 重试当前页
            print(f'[CSQAQ] HTTP Error: {e}')
            break
        except Exception as e:
            print(f'[CSQAQ] Error: {e}')
            break
    
    print(f'[CSQAQ] Total {len(all_items)} items with selling data')
    return all_items

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
            print(f'[WARN] ECO_PRIVATE_KEY_B64 decode failed: {e}')
    # 尝试本地文件
    for path in ['eco_private.pem', '../eco_private.pem', '../../eco_private_key.pem']:
        full = os.path.join(SCRIPT_DIR, path)
        if os.path.exists(full):
            try:
                with open(full, 'rb') as f:
                    _eco_key = RSA.import_key(f.read())
                print(f'[INFO] Loaded ECO key from {full}')
                return _eco_key
            except:
                pass
    return None

def sign_eco(params, key):
    sign_str = '&'.join(f'{k}={json.dumps(v, separators=(",",":"), ensure_ascii=False) if isinstance(v, (list,dict)) else v}'
                       for k, v in sorted(params.items(), key=lambda x: x[0].lower()) if v not in (None, ''))
    sig = pkcs1_15.new(key).sign(SHA256.new(sign_str.encode('utf-8')))
    return base64.b64encode(sig).decode()

def fetch_eco():
    key = get_eco_key()
    if not key:
        print('[ERROR] ECO key not found')
        return None
    ts = str(int(time.time()))
    params = {'PartnerId': PARTNER_ID, 'Timestamp': ts, 'GameID': '730', 'Sign': sign_eco({'PartnerId': PARTNER_ID, 'Timestamp': ts, 'GameID': '730'}, key)}
    try:
        with urllib.request.urlopen(urllib.request.Request(f'{ECO_BASE}/Api/Market/GetHashNameAndPriceList',
            data=json.dumps(params).encode(), headers={'Content-Type': 'application/json'}), context=ctx, timeout=30) as r:
            items = json.loads(r.read().decode('utf-8')).get('ResultData', [])
            print(f'[ECO] Got {len(items)} items')
            return items
    except Exception as e:
        print(f'[ECO] Error: {e}')
        return None

# ════════════════════ 选品筛选 ════════════════════

def get_price(item):
    return float(item.get('Price') or item.get('MarketComprePrice') or 0)

def filter_items_eco(eco_items, csqaq_selling):
    """
    按规则筛选饰品（使用 CSQAQ 的在售量数据）
    eco_items: ECO 返回的饰品列表（含价格）
    csqaq_selling: CSQAQ 返回的在售量字典 {id: {...}}
    """
    filtered, excluded = [], {'price': 0, 'type': 0, 'selling': 0, 'no_csqaq': 0}
    
    # 构建 name → 在售量 的映射（CSQAQ 的 name 可能乱码，需要模糊匹配）
    # 策略：用 ECO 的 GoodsName 去匹配 CSQAQ 的 name
    # 由于编码问题，这里简化处理：直接用 ECO 自身的 SellingTotal 作为 fallback
    
    # 先构建 CSQAQ 的 name 到在售量的映射
    csqaq_by_name = {}
    for v in csqaq_selling.values():
        name = v.get('name', '')
        if name:
            csqaq_by_name[name] = v['total_sell']
    
    for item in eco_items:
        name = item.get('HashName', '')
        goods_name = item.get('GoodsName', '')
        price = get_price(item)
        
        # 尝试从 CSQAQ 获取在售量
        # 先用 GoodsName 匹配，再用 HashName 匹配
        selling = csqaq_by_name.get(goods_name, 0)
        if not selling:
            # 尝试用 HashName 的部分匹配
            for csq_name, csq_sell in csqaq_by_name.items():
                if goods_name in csq_name or csq_name in goods_name:
                    selling = csq_sell
                    break
        
        # 如果 CSQAQ 没有，用 ECO 自身的在售量作为 fallback
        if not selling:
            selling = int(item.get('SellingTotal') or 0)
            if selling > 0:
                excluded['no_csqaq'] += 1
        
        # 规则1：排除价格 < 1 元
        if price < MIN_PRICE:
            excluded['price'] += 1
            continue
        
        # 规则2：排除暗金和纪念品
        if 'StatTrak' in name or 'Souvenir' in name:
            excluded['type'] += 1
            continue
        
        # 判断是否贴纸
        is_sticker = name.startswith('Sticker |')
        
        # 规则4：贴纸在售量 > 100
        if is_sticker:
            if selling <= STICKER_MIN_SELLING:
                excluded['selling'] += 1
                continue
        else:
            # 规则3：非贴纸按价格区间过滤
            passed = False
            for min_p, max_p, min_s in PRICE_THRESHOLDS:
                if min_p <= price < max_p:
                    if selling >= min_s:
                        passed = True
                    break
            if not passed:
                excluded['selling'] += 1
                continue
        
        # 添加 CSQAQ 在售量到 item（用于后续权重计算）
        item['CSQAQ_SellingTotal'] = selling
        filtered.append(item)
    
    print(f'[FILTER] ECO={len(eco_items)} → Filtered={len(filtered)} '
          f'(excluded: price={excluded["price"]}, type={excluded["type"]}, '
          f'selling={excluded["selling"]}, no_csqaq={excluded["no_csqaq"]})')
    return filtered

# ════════════════════ 指数计算 ════════════════════

def calc_weighted_value(items, weights):
    """计算加权市值（使用 CSQAQ 在售量作为权重）"""
    total = 0
    for item in items:
        price = get_price(item)
        if price <= 0:
            continue
        # 优先使用 CSQAQ 在售量，其次用 weights，最后 fallback 到当前在售量
        name = item.get('HashName', '')
        if name in weights:
            weight = weights[name]
        else:
            weight = item.get('CSQAQ_SellingTotal', int(item.get('SellingTotal') or 0))
        total += price * max(weight, 1)
    return round(total, 2)

def calc_index(current_items, base_data):
    """计算指数"""
    if not base_data:
        # 首次：当前即为基期
        weights = {i.get('HashName', ''): int(i.get('SellingTotal') or 0) for i in current_items}
        mv = calc_weighted_value(current_items, weights)
        return {'index': 1000.0, 'change_pct': 0.0, 'current_mv': mv, 'base_mv': mv, 
                'weights': weights, 'total_items': len(current_items)}
    
    # 用基期权重计算当前市值
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

# ════════════════════ 涨跌统计 ════════════════════

def calc_changes(current, prev_items):
    """计算涨跌分布"""
    if not prev_items:
        return {'gainers': 0, 'losers': 0, 'unchanged': 0, 'top_gainers': [], 'top_losers': []}
    
    prev_map = {i.get('HashName'): i for i in prev_items}
    changes, gainers, losers, unchanged = [], 0, 0, 0
    
    for item in current:
        name = item.get('HashName', '')
        price = get_price(item)
        prev = prev_map.get(name)
        if not prev or price <= 0:
            continue
        prev_price = get_price(prev)
        if prev_price <= 0:
            continue
            
        chg = (price - prev_price) / prev_price * 100
        changes.append({'name': name[:35], 'price': round(price, 2), 'change': round(chg, 2)})
        
        if chg > 0.1: gainers += 1
        elif chg < -0.1: losers += 1
        else: unchanged += 1
    
    changes.sort(key=lambda x: x['change'], reverse=True)
    return {
        'gainers': gainers, 'losers': losers, 'unchanged': unchanged,
        'top_gainers': changes[:10], 'top_losers': changes[-10:][::-1]
    }

def calc_selling_stats(current, prev):
    """在售量变化"""
    curr_s = sum(int(i.get('SellingTotal') or 0) for i in current)
    prev_s = sum(int(i.get('SellingTotal') or 0) for i in prev) if prev else 0
    delta = curr_s - prev_s
    return {
        'total_selling': curr_s, 'total_selling_prev': prev_s,
        'total_selling_delta': delta,
        'total_selling_delta_pct': round(delta / prev_s * 100, 2) if prev_s else 0
    }

def calc_trending(current, prev, top_n=15):
    """热门/冷门"""
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
        changes.append({
            'hash_name': name, 'goods_name': item.get('GoodsName', name),
            'price': get_price(item), 'current_selling': curr_s, 'prev_selling': prev_s,
            'selling_delta': curr_s - prev_s,
            'selling_delta_pct': round((curr_s - prev_s) / prev_s * 100, 1) if prev_s else (999 if curr_s > prev_s else -999)
        })
    changes.sort(key=lambda x: x['selling_delta'], reverse=True)
    return {'hot': changes[:top_n], 'cold': changes[-top_n:][::-1]}

# ════════════════════ 存储 ════════════════════

def load_json(path, default=None):
    """通用加载JSON"""
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return default

def save_json(path, data):
    """通用保存JSON"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_prev_items(date_str):
    """加载上一小时数据（支持跨日）"""
    now = datetime.now()
    prev = now - timedelta(hours=1)
    # 如果是0点，上一小时是昨天23点
    if now.hour == 0:
        prev_date = prev.strftime('%Y-%m-%d')
    else:
        prev_date = date_str
    path = os.path.join(HIST_DIR, f'{prev_date}_{prev.strftime("%H")}00.json')
    data = load_json(path, {})
    return data.get('items')

def save_snapshot(date_str, hour, items, index_info, changes, selling, trending):
    """保存小时快照（精简：只存必要字段）"""
    # 精简 items：只存 HashName, Price, SellingTotal 用于对比
    mini_items = [{'HashName': i.get('HashName'), 'Price': get_price(i), 
                   'SellingTotal': int(i.get('SellingTotal') or 0)} for i in items]
    
    path = os.path.join(HIST_DIR, f'{date_str}_{hour}00.json')
    save_json(path, {
        'time': f'{hour}:00', 'timestamp': int(time.time()),
        'items': mini_items,  # 精简后的items
        'index': index_info['index'], 'change_pct': index_info['change_pct'],
        'total_market_value': index_info['current_mv'],
        'change_stats': changes, 'selling_stats': selling, 'trending': trending
    })
    print(f'[SAVE] {path}')
    return path

def ensure_base(items, index_info):
    """创建基期（使用 CSQAQ 在售量作为权重）"""
    path = os.path.join(HIST_DIR, 'base.json')
    if os.path.exists(path):
        return load_json(path)
    
    # 使用 CSQAQ 在售量作为权重
    weights = {}
    for i in items:
        name = i.get('HashName', '')
        # 优先使用 CSQAQ 在售量
        selling = i.get('CSQAQ_SellingTotal', int(i.get('SellingTotal') or 0))
        if name and selling > 0:
            weights[name] = selling
    
    data = {
        'base_date': datetime.now().strftime('%Y-%m-%d'),
        'weights': weights,
        'base_mv': index_info['current_mv'],
        'total_items': len(items),
        'data_source': 'CSQAQ_Selling'  # 标记数据来源
    }
    save_json(path, data)
    print(f'[BASE] Created with {len(weights)} weights (CSQAQ selling)')
    return data

def update_series(date_str, index_info, reset=False):
    """更新指数序列"""
    path = os.path.join(INDEX_DIR, f'{date_str}.json')
    if reset:
        data = {'date': date_str, 'series': []}  # 新基期：清空
    else:
        data = load_json(path, {'date': date_str, 'series': []})
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
    """同步到 market.json"""
    path = os.path.join(DATA_DIR, 'market.json')
    market = load_json(path, {})
    
    # 构建 OHLC（简化：open=close=high=low=index）
    ohlc, vol_bar, max_mv = [], [], max((s.get('market_value') or 1) for s in series) if series else 1
    for s in series:
        ohlc.append({'date': date_str, 'dateFull': f"{date_str} {s.get('time','00:00')}",
                     'open': s['index'], 'close': s['index'], 'high': s['index'], 'low': s['index']})
        vol_bar.append(round(s.get('market_value', 0) / max_mv * 1000))
    
    last = series[-1] if series else {}
    market['index'] = {
        'latest': index_info['index'],
        'change': last.get('change_pct', 0),
        'change_pct': last.get('change_pct', 0),
        'market_value': index_info['current_mv'],
        'total_items': index_info['total_items'],
        'updated': datetime.now().strftime('%Y-%m-%dT%H:%M:%S+08:00'),
        'ohlc': ohlc, 'volBar': vol_bar,
        'volColor': ['#f87171' if v > 500 else '#52525b' for v in vol_bar],
        'series': series, 'selling': selling or {}, 'trending': trending or {'hot': [], 'cold': []}
    }
    market['index_updated'] = int(time.time() * 1000)
    save_json(path, market)
    print('[MKT] Updated')
    return path

# ════════════════════ MAIN ════════════════════

def main():
    print('=== CS2 Market Index v3.2 (CSQAQ Selling) ===')
    date_str = datetime.now().strftime('%Y-%m-%d')
    hour = datetime.now().strftime('%H')
    
    # 1. 获取 CSQAQ 在售量数据（用于筛选）
    csqaq_selling = fetch_csqaq_selling()
    if not csqaq_selling:
        print('[ERROR] Failed to fetch CSQAQ selling data')
        return 1
    
    # 2. 获取 ECO 价格数据
    eco_items = fetch_eco()
    if not eco_items:
        return 1
    
    # 3. 用 CSQAQ 在售量筛选 ECO 数据
    filtered = filter_items_eco(eco_items, csqaq_selling)
    
    # 4. 加载基期
    base = load_json(os.path.join(HIST_DIR, 'base.json'))
    
    # 5. 计算指数
    idx = calc_index(filtered, base)
    print(f'[INDEX] {idx["index"]:.2f} ({idx["change_pct"]:+.2f}%) MV={idx["current_mv"]:,.0f}')
    
    # 6. 加载上一小时（自动跨日）
    prev = load_prev_items(date_str)
    
    # 7. 计算统计
    changes = calc_changes(filtered, prev)
    selling = calc_selling_stats(filtered, prev)
    trending = calc_trending(filtered, prev)
    print(f'[STATS] selling={selling["total_selling"]:,} Δ{selling["total_selling_delta"]:+,} hot={len(trending["hot"])}')
    
    # 8. 保存
    snap = save_snapshot(date_str, hour, filtered, idx, changes, selling, trending)
    
    # 9. 确保基期
    is_new_base = False
    if not base:
        base = ensure_base(filtered, idx)
        idx['weights'] = base['weights']
        is_new_base = True
    
    # 10. 更新序列并同步（新基期时清空当天series）
    series = update_series(date_str, idx, reset=is_new_base)
    market = sync_market(date_str, idx, series, selling, trending)
    
    print(f'[DONE] {snap}, {market}')
    return 0

if __name__ == '__main__':
    sys.exit(main())
