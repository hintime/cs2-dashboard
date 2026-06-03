#!/usr/bin/env python3
"""生成 market_scan.json（全市场扫描快照 + 分类统计 + 涨跌榜）"""
import json, os, sys, time

DATA_DIR = os.path.dirname(os.path.abspath(__file__))

def read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def write_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

def classify(hn):
    if not hn: return 'other'
    if 'Knife' in hn: return 'knife'
    gl = ['Gloves', 'Hand Wraps', 'Sport Gloves', 'Specialist Gloves', 'Moto Gloves', 'Driver Gloves', 'Bloodhound Gloves']
    if any(g in hn for g in gl): return 'glove'
    if hn.startswith('Sticker'): return 'sticker'
    if any(c in hn for c in ['Case', 'Container', 'Package']): return 'case'
    if 'Music Kit' in hn: return 'musickit'
    if any(c in hn for c in ['Charm', 'Pin']): return 'charm'
    if 'Graffiti' in hn: return 'graffiti'
    if 'Patch' in hn: return 'patch'
    if 'Terminal' in hn: return 'other'
    # 探员：无磨损等级 + 前缀不是武器
    wear_words = ['Factory New', 'Minimal Wear', 'Field-Tested', 'Well-Worn', 'Battle-Scarred',
                  '崭新出厂', '略有磨损', '久经沙场', '破损不堪', '战痕累累']
    if not any(w in hn for w in wear_words):
        weapon_ps = ['AK-47', 'M4A4', 'M4A1-S', 'AWP', 'AUG', 'SG ', 'FAMAS', 'Galil', 'SSG', 'SCAR', 'G3SG1',
                     'P250', 'P2000', 'USP', 'Glock', 'Desert Eagle', 'Five-SeveN', 'CZ75', 'Dual Berettas', 'Tec-9', 'R8',
                     'MP5', 'MP7', 'MP9', 'MAC-10', 'PP-', 'UMP', 'P90',
                     'Nova', 'XM1014', 'MAG-7', 'Sawed-Off', 'Negev', 'M249',
                     'Zeus', 'Flashbang', 'Smoke', 'HE Grenade', 'Molotov', 'Incendiary', 'Decoy', '★']
        pref = hn.split(' | ')[0].strip() if ' | ' in hn else hn.split('|')[0].strip()
        if not any(pref.startswith(wp) for wp in weapon_ps):
            return 'agent'
    return 'weapon'

def is_boring(name):
    kw = ['武器箱', ' Capsule', '胶囊', '钥匙', 'Terminal', 'Music Kit', 'Charm', 'Pin', 'Sticker', '印花', 'Patch', '布章']
    return any(k in (name or '') for k in kw)

# 不参与全量扫描的品类（所有面板都不显示）
SKIP_CATS = {'sticker', 'musickit', 'charm', 'graffiti', 'case', 'patch'}

def _is_valid_scan_item(it):
    """全量扫描应排除的品类 / 磨损等级"""
    if not isinstance(it, dict): return False
    hn = it.get('HashName', '')
    c = classify(hn)
    if c in SKIP_CATS:  # 印花/音乐盒/挂件
        return False
    if is_boring(hn + (it.get('GoodsName') or '')):  # 终端机/武器箱等
        return False
    # 排除 破损不堪(WW) / 战痕累累(BS) / 纪念品
    if 'Battle-Scarred' in hn or '战痕累累' in (it.get('GoodsName') or ''):
        return False
    if 'Well-Worn' in hn or '破损不堪' in (it.get('GoodsName') or ''):
        return False
    if 'Souvenir' in hn:
        return False
    return True

def main():
    cat = read_json(os.path.join(DATA_DIR, 'eco_catalog.json'))
    if not isinstance(cat, list):
        print('[SCAN] eco_catalog.json not found or invalid')
        return

    # 先过滤全量数据
    valid = [it for it in cat if _is_valid_scan_item(it)]
    print(f'[SCAN] Total: {len(cat)}, Valid: {len(valid)}')

    prices = [it.get('Price', 0) for it in valid if isinstance(it, dict) and it.get('Price', 0) > 0]
    tiers = {'<10': 0, '10-50': 0, '50-200': 0, '200-1000': 0, '1000+': 0}
    for p in prices:
        if p < 10: tiers['<10'] += 1
        elif p < 50: tiers['10-50'] += 1
        elif p < 200: tiers['50-200'] += 1
        elif p < 1000: tiers['200-1000'] += 1
        else: tiers['1000+'] += 1

    # 分类统计
    cat_stats = {}
    for it in valid:
        if not isinstance(it, dict): continue
        hn = it.get('HashName', '')
        c = classify(hn)
        if c not in cat_stats:
            cat_stats[c] = {'count': 0, 'total_price': 0, 'price_count': 0}
        cat_stats[c]['count'] += 1
        p = it.get('Price', 0) or 0
        if p > 0:
            cat_stats[c]['total_price'] += p
            cat_stats[c]['price_count'] += 1

    # 精简分类输出
    cat_labels = {'weapon': '武器', 'knife': '刀', 'glove': '手套', 'sticker': '贴纸',
                  'case': '箱子', 'musickit': '音乐盒', 'charm': '挂件', 'graffiti': '涂鸦',
                  'agent': '探员', 'patch': '布章', 'other': '其他'}
    categories = {}
    for k, v in cat_stats.items():
        if k in SKIP_CATS:
            continue
        label = cat_labels.get(k, k)
        categories[label] = {
            'count': v['count'],
            'avg_p': round(v['total_price'] / v['price_count'], 1) if v['price_count'] > 0 else 0
        }

    # 在售TOP10（从有效数据中取）
    with_sell = [it for it in valid if isinstance(it, dict) and it.get('SellingTotal', 0) > 0]
    by_sell = sorted(with_sell, key=lambda x: x.get('SellingTotal', 0), reverse=True)[:10]
    top_sell = [{'n': (it.get('GoodsName') or it.get('HashName', ''))[:30], 's': it.get('SellingTotal', 0), 'p': it.get('Price', 0)} for it in by_sell]

    # 涨跌榜（从 price_history.json 计算，不依赖外部 API）
    movers = []
    # 构建 英文→中文 映射
    name_map = {}
    for it in cat:
        hn = it.get('HashName', '')
        gn = it.get('GoodsName', '')
        if hn and gn:
            name_map[hn] = gn
    
    ph_file = os.path.join(DATA_DIR, 'price_history.json')
    try:
        ph = read_json(ph_file)
        gains = []
        # 取 1 天前的价格做日涨跌对比
        cutoff = time.time() - 86400  # 1天前
        for name, h in ph.items():
            if not isinstance(h, dict): continue
            raw_eco = h.get('eco') or []
            eco_prices = [(e.get('t',''), e.get('p',0)) for e in raw_eco if isinstance(e, dict) and e.get('p', 0) > 0]
            if len(eco_prices) < 10: continue  # 至少10个数据点
            last_p = eco_prices[-1][1]
            # 找最接近 1 天前的价格
            prev_p = 0
            best_diff = None
            for ts, p in eco_prices[:-1]:
                try:
                    t = time.mktime(time.strptime(ts[:16], '%Y-%m-%dT%H:%M')) if 'T' in ts else time.mktime(time.strptime(ts[:16], '%Y-%m-%d %H:%M'))
                except:
                    continue
                diff = abs(t - cutoff)
                if best_diff is None or diff < best_diff:
                    best_diff = diff
                    prev_p = p
            if prev_p <= 0 or last_p <= 0: continue
            eco_chg = (last_p - prev_p) / prev_p * 100
            if abs(eco_chg) < 0.01: continue
            cn = name_map.get(name, name)
            gains.append((cn[:24], round(eco_chg, 1), last_p))
        gains.sort(key=lambda x: x[1], reverse=True)
        gainers = [{'n': g[0], 'r7': g[1], 'p': g[2]} for g in gains if g[1] > 0][:10]
        losers = [{'n': g[0], 'r7': g[1], 'p': g[2]} for g in gains if g[1] < 0][-10:][::-1]
        movers = {'gainers': gainers, 'losers': losers}
    except Exception as e:
        print(f'[SCAN] movers error: {e}')

    prices_sorted = sorted(prices)
    n = len(prices_sorted)
    scan = {
        'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'total': len(valid),
        'tracked': len(read_json(os.path.join(DATA_DIR, 'eco_tracked.json'))) if os.path.exists(os.path.join(DATA_DIR, 'eco_tracked.json')) else 0,
        'tiers': tiers,
        'avg_p': round(sum(prices) / len(prices), 2) if prices else 0,
        'median_p': round(prices_sorted[n//2], 2) if n > 0 else 0,
        'min_p': round(prices_sorted[0], 2) if n > 0 else 0,
        'max_p': round(prices_sorted[-1], 2) if n > 0 else 0,
        'top_sell': top_sell,
        'categories': categories,
        'movers': movers,
    }

    write_json(os.path.join(DATA_DIR, 'market_scan.json'), scan)
    print(f'[SCAN] Saved: {len(valid)} items (from {len(cat)}), {len(prices)} with prices, {len(categories)} categories, movers: {bool(movers)}')

if __name__ == '__main__':
    main()
