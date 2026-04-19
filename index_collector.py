#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CS2 大盘指数收集器
- 每小时从ECO获取全量价格数据（36,000+条）
- 计算市场指数快照
- 存储到 index_history/YYYY-MM-DD.json
- 推送GitHub

指数类型：
- 市值指数（总市值变化）
- 等权指数（平均价格变化）
- 涨跌分布统计
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
INDEX_DIR = os.path.join(DATA_DIR, 'index_history')

# ECO API
ECO_BASE = 'https://openapi.ecosteam.cn'

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# ═══════════════ ECO SIGNING ═══════════════
_eco_key = None

def get_eco_key():
    """Load ECO private key from env or file"""
    global _eco_key
    if _eco_key:
        return _eco_key
    
    # Try environment variable (base64 encoded)
    key_b64 = os.environ.get('ECO_PRIVATE_KEY_B64', '')
    if key_b64:
        try:
            key_der = base64.b64decode(key_b64)
            _eco_key = RSA.import_key(key_der)
            return _eco_key
        except Exception as e:
            print(f'[WARN] Failed to decode ECO_PRIVATE_KEY_B64: {e}')
    
    # Try local file
    key_paths = [
        os.path.join(SCRIPT_DIR, 'eco_private.pem'),
        os.path.join(DATA_DIR, 'eco_private.pem'),
        os.path.join(SCRIPT_DIR, '..', 'eco_private_key.pem'),  # workspace root
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
    """ECO API签名：参数按key字母序排序，SHA256withRSA签名"""
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
    """获取ECO全量价格数据"""
    key = get_eco_key()
    if not key:
        print('[ERROR] ECO private key not found')
        return None
    
    url = f'{ECO_BASE}/Api/Market/GetHashNameAndPriceList'
    ts = str(int(time.time()))  # ECO API需要秒级时间戳
    
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
def calc_index_snapshot(items, prev_items=None):
    """计算指数快照"""
    if not items:
        return None
    
    # 基础统计
    total_items = len(items)
    total_market_value = 0  # 总市值 = Σ(price × 在售量)
    total_price = 0
    total_selling = 0
    price_changes = []
    
    # 按价格区间统计
    price_brackets = {
        'under_50': 0,
        '50_100': 0,
        '100_500': 0,
        '500_1000': 0,
        'over_1000': 0
    }
    
    for item in items:
        price = float(item.get('Price', 0) or item.get('MarketComprePrice', 0) or 0)
        selling = int(item.get('SellingTotal', 0) or 0)
        
        if price <= 0:
            continue
        
        total_market_value += price * max(selling, 1)
        total_price += price
        total_selling += selling
        
        # 价格区间统计
        if price < 50:
            price_brackets['under_50'] += 1
        elif price < 100:
            price_brackets['50_100'] += 1
        elif price < 500:
            price_brackets['100_500'] += 1
        elif price < 1000:
            price_brackets['500_1000'] += 1
        else:
            price_brackets['over_1000'] += 1
    
    avg_price = total_price / total_items if total_items > 0 else 0
    
    # 涨跌统计（需要历史数据）
    gainers = 0
    losers = 0
    unchanged = 0
    top_gainers = []
    top_losers = []
    
    if prev_items:
        prev_map = {i.get('HashName'): i for i in prev_items}
        
        for item in items:
            name = item.get('HashName')
            price = float(item.get('Price', 0) or item.get('MarketComprePrice', 0) or 0)
            prev = prev_map.get(name)
            
            if prev and price > 0:
                prev_price = float(prev.get('Price', 0) or prev.get('MarketComprePrice', 0) or 0)
                if prev_price > 0:
                    change_pct = (price - prev_price) / prev_price * 100
                    price_changes.append({
                        'name': name,
                        'price': price,
                        'change_pct': change_pct
                    })
                    
                    if change_pct > 0.1:
                        gainers += 1
                    elif change_pct < -0.1:
                        losers += 1
                    else:
                        unchanged += 1
        
        # 排序获取Top涨跌榜
        price_changes.sort(key=lambda x: x['change_pct'], reverse=True)
        top_gainers = price_changes[:10]
        top_losers = price_changes[-10:][::-1]
    
    snapshot = {
        'time': datetime.now().strftime('%H:%M'),
        'timestamp': int(time.time()),
        'total_items': total_items,
        'market_value': round(total_market_value, 2),
        'avg_price': round(avg_price, 2),
        'total_selling': total_selling,
        'price_distribution': price_brackets,
        'change_stats': {
            'gainers': gainers,
            'losers': losers,
            'unchanged': unchanged
        }
    }
    
    if top_gainers:
        snapshot['top_gainers'] = [{
            'name': g['name'][:30],
            'price': g['price'],
            'change': round(g['change_pct'], 2)
        } for g in top_gainers]
    
    if top_losers:
        snapshot['top_losers'] = [{
            'name': l['name'][:30],
            'price': l['price'],
            'change': round(l['change_pct'], 2)
        } for l in top_losers]
    
    return snapshot

def load_prev_day_data(date_str):
    """加载前一天的数据"""
    prev_date = (datetime.strptime(date_str, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
    prev_file = os.path.join(INDEX_DIR, f'{prev_date}.json')
    
    if os.path.exists(prev_file):
        try:
            with open(prev_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 返回最后一个快照的数据
                if data.get('snapshots'):
                    last = data['snapshots'][-1]
                    # 如果有保存的样本数据，返回它
                    return {'items': last.get('items_sample', [])}
        except Exception as e:
            print(f'[WARN] Failed to load prev day data: {e}')
    
    return None

def save_index_data(date_str, snapshot, items_sample=None):
    """保存指数数据"""
    os.makedirs(INDEX_DIR, exist_ok=True)
    index_file = os.path.join(INDEX_DIR, f'{date_str}.json')
    
    # 加载现有数据
    data = {'date': date_str, 'snapshots': []}
    if os.path.exists(index_file):
        try:
            with open(index_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except:
            pass
    
    # 追加新快照
    data['snapshots'].append(snapshot)
    
    # 只保留当天最近24个快照（每小时一个）
    if len(data['snapshots']) > 24:
        data['snapshots'] = data['snapshots'][-24:]
    
    # 如果是当天第一个快照，保存样本数据用于明天涨跌计算
    if items_sample and len(data.get('snapshots', [])) == 1:
        data['items_sample'] = items_sample
    
    # 保存
    with open(index_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f'[SAVE] {index_file} ({len(data["snapshots"])} snapshots)')
    return index_file

# ═══════════════ GIT PUSH ═══════════════
def git_push(files_changed, msg):
    """Push files to GitHub"""
    if not files_changed:
        print('[INFO] No files to push')
        return
    
    # Check if we're in a git repo
    if not os.path.exists(os.path.join(DATA_DIR, '.git')):
        print('[INFO] Initializing git repo...')
        subprocess.run(['git', 'init'], cwd=DATA_DIR, capture_output=True)
        subprocess.run(['git', 'remote', 'add', 'origin', f'https://github.com/{REPO}.git'], cwd=DATA_DIR, capture_output=True)
    
    # Add and commit
    for f in files_changed:
        subprocess.run(['git', 'add', f], cwd=DATA_DIR, capture_output=True)
    
    result = subprocess.run(['git', 'commit', '-m', msg], cwd=DATA_DIR, capture_output=True, text=True)
    if 'nothing to commit' in result.stdout or result.returncode != 0:
        print(f'[GIT] {result.stdout.strip()}')
        return
    
    # Pull rebase and push
    subprocess.run(['git', 'pull', '--rebase'], cwd=DATA_DIR, capture_output=True)
    
    if GH_TOKEN:
        push_url = f'https://x-access-token:{GH_TOKEN}@github.com/{REPO}.git'
        subprocess.run(['git', 'push', push_url], cwd=DATA_DIR, capture_output=True)
    else:
        subprocess.run(['git', 'push'], cwd=DATA_DIR, capture_output=True)
    
    print(f'[GIT] Pushed: {msg}')

# ═══════════════ MAIN ═══════════════
def main():
    print('=== CS2 Index Collector ===')
    
    # 当前日期
    date_str = datetime.now().strftime('%Y-%m-%d')
    
    # 获取全量数据
    items = fetch_eco_full_prices()
    if not items:
        print('[ERROR] No data fetched')
        return 1
    
    # 加载前一天数据（用于计算涨跌）
    prev_data = load_prev_day_data(date_str)
    prev_items = prev_data.get('items') if prev_data else None
    
    # 计算指数快照
    snapshot = calc_index_snapshot(items, prev_items)
    if not snapshot:
        print('[ERROR] Failed to calc index')
        return 1
    
    # 保存指数数据（第一次运行时保存样本）
    is_first = not os.path.exists(os.path.join(INDEX_DIR, f'{date_str}.json'))
    sample_data = items[:500] if is_first else None  # 保存500个样本用于明天涨跌计算
    index_file = save_index_data(date_str, snapshot, sample_data)
    
    # Git push
    git_push([index_file], f'chore: update index {date_str} {snapshot["time"]}')
    
    # 输出摘要
    print(f'')
    print(f'[INDEX] Market Snapshot {date_str} {snapshot["time"]}')
    print(f'  Total Items: {snapshot["total_items"]:,}')
    print(f'  Market Value: {snapshot["market_value"]:,.0f} CNY')
    print(f'  Avg Price: {snapshot["avg_price"]:.2f} CNY')
    print(f'  Total Selling: {snapshot["total_selling"]:,}')
    
    if snapshot.get('change_stats'):
        cs = snapshot['change_stats']
        print(f'  Changes: UP {cs["gainers"]} / DOWN {cs["losers"]} / NC {cs["unchanged"]}')
    
    print(f'')
    return 0

if __name__ == '__main__':
    sys.exit(main())
