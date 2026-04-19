#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CS2 大盘指数收集器 v2（通用版公式）

指数 = (当前总市值 ÷ 基期总市值) × 1000
市值 = Σ(每只饰品 BUFF 底价 × 在售数量)

存储结构：
  market_history/
    {YYYY-MM-DD_HH}00.json   ← 每小时快照（含完整items用于次日涨跌）
    base.json                ← 基期快照（所有快照的参考基准）

指数历史：
  index_history/
    {YYYY-MM-DD}.json        ← 每日指数时间序列
"""
import json, time, base64, urllib.request, urllib.error, subprocess, os, sys, ssl
from datetime import datetime, timedelta
from hashlib import sha256
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256

# ═══════════════ CONFIG ═══════════════
PARTNER_ID = 'da740aa96cc14cc594371f95469c90ac'
GH_TOKEN = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN', '')
REPO = 'hintime/cs2-dashboard'
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, '..') if SCRIPT_DIR.endswith('.github') else SCRIPT_DIR
HIST_DIR = os.path.join(DATA_DIR, 'market_history')  # 原始快照
INDEX_DIR = os.path.join(DATA_DIR, 'index_history')  # 指数序列
ECO_BASE = 'https://openapi.ecosteam.cn'

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# ═══════════════ ECO SIGNING ═══════════════
_eco_key = None

def get_eco_key():
    global _eco_key
    if _eco_key:
        return _eco_key
    key_b64 = os.environ.get('ECO_PRIVATE_KEY_B64', '')
    if key_b64:
        try:
            key_der = base64.b64decode(key_b64)
            _eco_key = RSA.import_key(key_der)
            return _eco_key
        except Exception as e:
            print(f'[WARN] Failed to decode ECO_PRIVATE_KEY_B64: {e}')
    key_paths = [
        os.path.join(SCRIPT_DIR, 'eco_private.pem'),
        os.path.join(DATA_DIR, 'eco_private.pem'),
        os.path.join(DATA_DIR, '..', 'eco_private_key.pem'),
        os.path.expanduser('~/.eco_key.pem')
    ]
    for path in key_paths:
        if os.path.exists(path):
            try:
                with open(path, 'rb') as f:
                    _eco_key = RSA.import_key(f.read())
                print(f'[INFO] Loaded ECO key from {path}')
                return _eco_key
            except Exception as e:
                print(f'[WARN] Failed to load key from {path}: {e}')
    return None

def sign_eco(params, private_key):
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
    signature = pkcs1_15.new(private_key).sign(h)
    return base64.b64encode(signature).decode()

def fetch_eco_full_prices():
    key = get_eco_key()
    if not key:
        print('[ERROR] ECO private key not found')
        return None
    url = f'{ECO_BASE}/Api/Market/GetHashNameAndPriceList'
    ts = str(int(time.time()))
    params = {
        'PartnerId': PARTNER_ID,
        'Timestamp': ts,
        'GameID': '730'
    }
    params['Sign'] = sign_eco(params, key)
    body = json.dumps(params).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            items = data.get('ResultData') or []
            print(f'[ECO] Got {len(items)} items')
            return items if len(items) > 0 else None
    except Exception as e:
        print(f'[ECO] Fetch error: {e}')
        return None

# ═══════════════ INDEX CALCULATION ═══════════════

def calc_market_value(items):
    """
    计算当前总市值
    市值 = Σ(BUFF底价 × 在售数量)
    """
    total_value = 0
    total_items = 0
    price_sum = 0

    for item in items:
        # Price: 优先用 Price(BUFF最低卖价), fallback 到 MarketComprePrice
        price = float(item.get('Price') or item.get('MarketComprePrice') or 0)
        selling = int(item.get('SellingTotal') or 0)

        if price <= 0:
            continue

        total_value += price * max(selling, 1)
        price_sum += price
        total_items += 1

    avg_price = price_sum / total_items if total_items > 0 else 0
    return {
        'total_market_value': round(total_value, 2),
        'avg_price': round(avg_price, 2),
        'total_items': total_items,
    }

def build_item_map(items):
    """为快速查找构建 HashName → 物品数据的映射"""
    return {i.get('HashName'): i for i in items}

def calc_index(current_items, base_items):
    """
    计算市值加权指数
    指数 = (当前总市值 ÷ 基期总市值) × 1000
    """
    curr = calc_market_value(current_items)
    base = calc_market_value(base_items) if base_items else None

    if base is None:
        # 无基期数据，第一期为基期，指数 = 1000
        index_value = 1000.0
        change_pct = 0.0
    else:
        if base['total_market_value'] > 0:
            index_value = (curr['total_market_value'] / base['total_market_value']) * 1000
            change_pct = (curr['total_market_value'] - base['total_market_value']) / base['total_market_value'] * 100
        else:
            index_value = 1000.0
            change_pct = 0.0

    return {
        'index': round(index_value, 2),
        'change_pct': round(change_pct, 2),
        'current_mv': curr['total_market_value'],
        'base_mv': base['total_market_value'] if base else 0,
        'avg_price': curr['avg_price'],
        'total_items': curr['total_items'],
    }

def calc_change_stats(current_items, prev_items):
    """
    计算涨跌分布（对比上一小时快照）
    """
    if not prev_items:
        return {'gainers': 0, 'losers': 0, 'unchanged': 0, 'top_gainers': [], 'top_losers': []}

    prev_map = build_item_map(prev_items)
    gainers, losers, unchanged = 0, 0, 0
    changes = []

    for item in current_items:
        name = item.get('HashName', '')
        price = float(item.get('Price') or item.get('MarketComprePrice') or 0)
        prev = prev_map.get(name)
        if not prev or price <= 0:
            continue
        prev_price = float(prev.get('Price') or prev.get('MarketComprePrice') or 0)
        if prev_price <= 0:
            continue

        change_pct = (price - prev_price) / prev_price * 100
        changes.append({'name': name, 'price': price, 'change_pct': change_pct})

        if change_pct > 0.1:
            gainers += 1
        elif change_pct < -0.1:
            losers += 1
        else:
            unchanged += 1

    changes.sort(key=lambda x: x['change_pct'], reverse=True)
    top_gainers = [{'name': c['name'][:35], 'price': round(c['price'], 2), 'change': round(c['change_pct'], 2)} for c in changes[:10]]
    top_losers = [{'name': c['name'][:35], 'price': round(c['price'], 2), 'change': round(c['change_pct'], 2)} for c in changes[-10:][::-1]]

    return {
        'gainers': gainers,
        'losers': losers,
        'unchanged': unchanged,
        'top_gainers': top_gainers,
        'top_losers': top_losers,
    }

def price_distribution(items):
    """按价格区间统计"""
    brackets = {'under_50': 0, '50_100': 0, '100_500': 0, '500_1000': 0, 'over_1000': 0}
    for item in items:
        price = float(item.get('Price') or item.get('MarketComprePrice') or 0)
        if price <= 0:
            continue
        if price < 50:
            brackets['under_50'] += 1
        elif price < 100:
            brackets['50_100'] += 1
        elif price < 500:
            brackets['100_500'] += 1
        elif price < 1000:
            brackets['500_1000'] += 1
        else:
            brackets['over_1000'] += 1
    return brackets

def calc_selling_stats(current_items, prev_items):
    """
    计算全市场在售量统计（作为成交量代理）
    delta > 0：有人在买（挂单被吃掉）
    delta < 0：有人上架新饰品
    """
    total_curr = sum(int(i.get('SellingTotal') or 0) for i in current_items)
    total_prev = sum(int(i.get('SellingTotal') or 0) for i in prev_items) if prev_items else 0
    delta = total_curr - total_prev
    return {
        'total_selling': total_curr,
        'total_selling_prev': total_prev,
        'total_selling_delta': delta,
        'total_selling_delta_pct': round(delta / total_prev * 100, 2) if total_prev > 0 else 0,
    }

def calc_trending_items(current_items, prev_items, top_n=15):
    """
    计算热门/冷门饰品（在售量变化最大/最小的饰品）
    hot：SellingTotal 增加最多的（被持续买入，卖方货源紧）
    cold：SellingTotal 减少最多的（卖方增多/买家减少）
    """
    if not prev_items:
        return {'hot': [], 'cold': []}
    prev_map = {i.get('HashName', ''): int(i.get('SellingTotal') or 0) for i in prev_items}
    changes = []
    for item in current_items:
        name = item.get('HashName', '')
        curr_s = int(item.get('SellingTotal') or 0)
        prev_s = prev_map.get(name, 0)
        delta = curr_s - prev_s
        if delta == 0:
            continue
        price = float(item.get('Price') or item.get('MarketComprePrice') or 0)
        changes.append({
            'hash_name': name,
            'goods_name': item.get('GoodsName', name),
            'price': price,
            'current_selling': curr_s,
            'prev_selling': prev_s,
            'selling_delta': delta,
            'selling_delta_pct': round(delta / prev_s * 100, 1) if prev_s > 0 else (999 if delta > 0 else -999),
        })
    changes.sort(key=lambda x: x['selling_delta'], reverse=True)
    return {'hot': changes[:top_n], 'cold': changes[-top_n:][::-1]}

# ═══════════════ STORAGE ═══════════════

def get_hourly_file(date_str):
    """获取当前小时快照文件名"""
    hour = datetime.now().strftime('%H')
    return os.path.join(HIST_DIR, f'{date_str}_{hour}00.json')

def load_prev_hour_items(date_str):
    """加载上一小时快照的items数据"""
    hour = datetime.now().strftime('%H')
    # 尝试当前小时-1
    prev_hour = int(hour) - 1
    if prev_hour < 0:
        prev_hour = 23
    prev_file = os.path.join(HIST_DIR, f'{date_str}_{prev_hour:02d}00.json')
    if os.path.exists(prev_file):
        try:
            with open(prev_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('items', [])
        except:
            pass
    return None

def load_base_items():
    """加载基期快照（第一个快照或 base.json）"""
    base_file = os.path.join(HIST_DIR, 'base.json')
    if os.path.exists(base_file):
        try:
            with open(base_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('items', [])
        except:
            pass
    return None

def save_hourly_snapshot(date_str, items, index_info, change_stats, selling_stats=None, trending=None):
    """保存每小时快照"""
    os.makedirs(HIST_DIR, exist_ok=True)
    hour = datetime.now().strftime('%H')
    file_path = os.path.join(HIST_DIR, f'{date_str}_{hour}00.json')

    snapshot = {
        'time': f'{hour}:00',
        'timestamp': int(time.time()),
        'items': items,  # 完整items用于次日涨跌计算
        'index': index_info['index'],
        'change_pct': index_info['change_pct'],
        'total_market_value': index_info['current_mv'],
        'avg_price': index_info['avg_price'],
        'total_items': index_info['total_items'],
        'price_distribution': price_distribution(items),
        'change_stats': change_stats,
        'selling_stats': selling_stats or {},
        'trending': trending or {'hot': [], 'cold': []},
    }

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f'[SAVE] {file_path}')
    return file_path

def ensure_base_updated(items, index_info):
    """确保基期快照存在（只在第一天或 base.json 不存在时更新）"""
    base_file = os.path.join(HIST_DIR, 'base.json')
    if not os.path.exists(base_file):
        base_data = {
            'base_date': datetime.now().strftime('%Y-%m-%d'),
            'items': items,
            'total_market_value': index_info['current_mv'],
            'index': 1000.0,
        }
        with open(base_file, 'w', encoding='utf-8') as f:
            json.dump(base_data, f, ensure_ascii=False, indent=2)
        print('[BASE] Created base.json (first snapshot = 1000)')

def update_index_series(date_str, index_info, change_stats):
    """更新每日指数时间序列"""
    os.makedirs(INDEX_DIR, exist_ok=True)
    index_file = os.path.join(INDEX_DIR, f'{date_str}.json')

    data = {'date': date_str, 'series': []}
    if os.path.exists(index_file):
        try:
            with open(index_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except:
            pass

    data['series'].append({
        'time': datetime.now().strftime('%H:%M'),
        'timestamp': int(time.time()),
        'index': index_info['index'],
        'change_pct': index_info['change_pct'],
        'market_value': index_info['current_mv'],
        'avg_price': index_info['avg_price'],
    })

    # 只保留当天48个点
    if len(data['series']) > 48:
        data['series'] = data['series'][-48:]

    with open(index_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'[IDX] {index_file} ({len(data["series"])} points)')

def sync_market_json(date_str, index_info, series_data, selling_stats=None, trending=None):
    """把指数数据写入 market.json（前端期望的格式）"""
    market_file = os.path.join(DATA_DIR, 'market.json')

    market = {}
    if os.path.exists(market_file):
        try:
            with open(market_file, 'r', encoding='utf-8') as f:
                market = json.load(f)
        except:
            pass

    # 构建 ohlc 数据（前端 renderMarket 期望的格式）
    ohlc = []
    vol_bar = []
    max_mv = max((s.get('market_value') or 1) for s in series_data) if series_data else 1

    for s in series_data:
        idx_val = s['index']
        mv = s.get('market_value') or 0
        # OHLC: 简化处理，open=close=high=low=指数值
        ohlc.append({
            'date': date_str,
            'dateFull': f"{date_str} {s.get('time','00:00')}",
            'open': idx_val,
            'close': idx_val,
            'high': idx_val,
            'low': idx_val,
        })
        # volBar: 用市值柱（归一化到 0-1000），颜色表示相对强弱
        vol_bar.append(round(mv / max_mv * 1000))

    # 取最后一条涨跌
    last = series_data[-1] if series_data else {}
    change_pct = last.get('change_pct', 0)
    change = change_pct  # 前端用的字段名

    market['index'] = {
        'latest': index_info['index'],
        'change': change,
        'change_pct': change_pct,
        'market_value': index_info['current_mv'],
        'avg_price': index_info['avg_price'],
        'total_items': index_info['total_items'],
        'ohlc': ohlc,
        'volBar': vol_bar,
        'volColor': [('#f87171' if v > 500 else '#52525b') for v in vol_bar],
        'series': series_data,
        # 在售量统计（作为成交量代理）
        'selling': selling_stats or {},
        # 热门/冷门饰品
        'trending': trending or {'hot': [], 'cold': []},
    }
    market['index_updated'] = int(time.time() * 1000)

    with open(market_file, 'w', encoding='utf-8') as f:
        json.dump(market, f, ensure_ascii=False, indent=2)
    print(f'[MKT] Updated market.json index block')
    return market_file

# ═══════════════ GIT PUSH ═══════════════

def git_push(files, msg):
    if not files:
        print('[GIT] Nothing to push')
        return
    if not os.path.exists(os.path.join(DATA_DIR, '.git')):
        subprocess.run(['git', 'init'], cwd=DATA_DIR, capture_output=True)
        subprocess.run(['git', 'remote', 'add', 'origin', f'https://github.com/{REPO}.git'], cwd=DATA_DIR, capture_output=True)
    for f in files:
        subprocess.run(['git', 'add', f], cwd=DATA_DIR, capture_output=True)
    result = subprocess.run(['git', 'commit', '-m', msg], cwd=DATA_DIR, capture_output=True, text=True)
    if 'nothing to commit' in result.stdout:
        print('[GIT] Nothing new to commit')
        return
    subprocess.run(['git', 'pull', '--rebase'], cwd=DATA_DIR, capture_output=True)
    if GH_TOKEN:
        push_url = f'https://x-access-token:{GH_TOKEN}@github.com/{REPO}.git'
        subprocess.run(['git', 'push', push_url], cwd=DATA_DIR, capture_output=True)
    else:
        subprocess.run(['git', 'push'], cwd=DATA_DIR, capture_output=True)
    print(f'[GIT] Pushed: {msg}')

# ═══════════════ MAIN ═══════════════

def main():
    print('=== CS2 Market Index Collector v2 ===')
    date_str = datetime.now().strftime('%Y-%m-%d')
    now_hour = datetime.now().strftime('%H')

    # 1. 获取全量数据
    items = fetch_eco_full_prices()
    if not items:
        print('[ERROR] No data fetched')
        return 1

    # 2. 获取基期数据（用于算指数）
    base_items = load_base_items()

    # 3. 获取上一小时数据（用于算涨跌）
    prev_items = load_prev_hour_items(date_str)

    # 4. 计算市值加权指数
    index_info = calc_index(items, base_items)
    print(f'[INDEX] Value={index_info["index"]:.2f} Change={index_info["change_pct"]:+.2f}%')
    print(f'[MV] Current={index_info["current_mv"]:,.0f} Base={index_info["base_mv"]:,.0f}')

    # 5. 计算涨跌分布
    change_stats = calc_change_stats(items, prev_items) if prev_items else {'gainers': 0, 'losers': 0, 'unchanged': 0, 'top_gainers': [], 'top_losers': []}

    # 6. 计算在售量变化（成交量代理）
    selling_stats = calc_selling_stats(items, prev_items)
    print(f'[SELLING] curr={selling_stats["total_selling"]:,} prev={selling_stats["total_selling_prev"]:,} delta={selling_stats["total_selling_delta"]:+,} ({selling_stats["total_selling_delta_pct"]:+.1f}%)')

    # 7. 计算热门/冷门饰品
    trending = calc_trending_items(items, prev_items, top_n=15)
    print(f'[TRENDING] hot={len(trending["hot"])} cold={len(trending["cold"])}')

    # 8. 保存快照
    snap_file = save_hourly_snapshot(date_str, items, index_info, change_stats, selling_stats, trending)

    # 7. 确保基期存在
    ensure_base_updated(items, index_info)

    # 8. 更新指数序列
    index_file = os.path.join(INDEX_DIR, f'{date_str}.json')
    series_data = []
    if os.path.exists(index_file):
        try:
            with open(index_file, 'r', encoding='utf-8') as f:
                d = json.load(f)
                series_data = d.get('series', [])
        except:
            pass

    # 9. 同步到 market.json（前端直接读取）
    market_file = sync_market_json(date_str, index_info, series_data, selling_stats, trending)

    # 10. Git push
    hour = now_hour
    git_push(
        [snap_file, os.path.join(HIST_DIR, 'base.json'), index_file, market_file],
        f'chore: market index {date_str} {hour}:00 idx={index_info["index"]:.2f}'
    )

    # 10. 输出摘要
    print('')
    print(f'=== {date_str} {hour}:00 ===')
    print(f'  Index:  {index_info["index"]:.2f}  ({index_info["change_pct"]:+.2f}% vs base)')
    print(f'  Mkt Cap: {index_info["current_mv"]:,.0f} CNY')
    print(f'  Avg Price: {index_info["avg_price"]:.2f} CNY')
    print(f'  Items: {index_info["total_items"]:,}')
    if change_stats.get('gainers') or change_stats.get('losers'):
        cs = change_stats
        print(f'  Changes vs prev hour: UP={cs["gainers"]} DOWN={cs["losers"]} NC={cs["unchanged"]}')
    print('')
    return 0

if __name__ == '__main__':
    sys.exit(main())
