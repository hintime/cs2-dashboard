#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Steam Market data fetcher + recommendation engine (no ECO/SteamDT dependency)
Uses ONLY Steam free public API
"""
import json, time, os, sys, urllib.request, urllib.parse, ssl

ctx = ssl.create_default_context()

DATA_DIR = os.path.dirname(os.path.abspath(__file__))

def http_get(url, timeout=15):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print(f'  [SM] GET error: {e}', file=sys.stderr)
        return {}

def fetch_steam_market_items(max_items=500, min_price=10.0, max_pages=10):
    """Paginate Steam Community Market search API for top items."""
    print(f'[SM] Fetching top {max_items} items (min_price={min_price:.0f} CNY)...')
    items = []
    page_size = 100
    
    for page in range(max_pages):
        if len(items) >= max_items:
            break
        
        start = page * page_size
        url = (f'https://steamcommunity.com/market/search/render/?'
               f'query=&start={start}&count={page_size}'
               f'&search_descriptions=0'
               f'&sort_column=popular&sort_dir=desc'
               f'&appid=730&norender=1')
        
        data = http_get(url, timeout=20)
        if not data or 'results' not in data:
            print(f'  [SM] Page {page}: no results, stopping')
            break
        
        results = data.get('results', [])
        if not results:
            break
        
        for r in results:
            name = r.get('name', '')
            # Exclude StatTrak/bad wear/cases/capsules
            if 'StatTrak' in name or 'Battle-Scarred' in name or 'Well-Worn' in name:
                continue
            if name.endswith(' Case') or name.endswith(' Capsule') or name.endswith(' Package') or name.endswith(' Pin') or 'Souvenir ' in name or 'Sticker | ' in name or 'Graffiti | ' in name or 'Patch | ' in name or 'Charm | ' in name:
                continue
            price = r.get('sell_price', 0) / 100  # API returns cents (fen)
            if price < min_price:
                continue
            items.append({
                'name': name,
                'price': price,
                'sell_listings': r.get('sell_listings', 0),
                'name_en': r.get('hash_name', name),  # English hash name
                'app_icon': r.get('asset_description', {}).get('icon_url', ''),
            })
            if len(items) >= max_items:
                break
        
        print(f'  [SM] Page {page}: {len(items)} collected ({len(items)}/{max_items})')
        time.sleep(1.5)
    
    print(f'[SM] Total: {len(items)} items')
    return items

def update_market_history(items, history_path):
    """Save daily price snapshot to history JSON."""
    today = time.strftime('%Y-%m-%d')
    
    if os.path.exists(history_path):
        with open(history_path, 'r', encoding='utf-8') as f:
            history = json.load(f)
    else:
        history = {}
    
    snapshot = {}
    for item in items:
        snapshot[item['name']] = {
            'price': item['price'],
            'sell_listings': item['sell_listings'],
        }
    
    history[today] = snapshot
    
    # Keep last 60 days
    dates = sorted(history.keys())
    while len(dates) > 60:
        del history[dates[0]]
        dates = dates[1:]
    
    with open(history_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    
    print(f'[SM] History: {today} saved, {len(snapshot)} items, {len(history)} days total')
    return history

def compute_alerts_from_history(history):
    """Compute price change alerts from history."""
    if not history or len(history) < 2:
        print('[SM] Alerts: need at least 2 days of history')
        return []
    
    dates = sorted(history.keys())
    today = dates[-1]
    
    alerts = []
    today_data = history[today]
    
    for name, today_info in today_data.items():
        a = {
            'name': name,
            'price': today_info['price'],
            'sell_listings': today_info.get('sell_listings', 0),
            'rate_1': 0, 'rate_7': 0, 'rate_30': 0,
        }
        
        # 1-day
        if len(dates) >= 2 and name in history.get(dates[-2], {}):
            old = history[dates[-2]][name]['price']
            if old > 0:
                a['rate_1'] = round((today_info['price'] - old) / old * 100, 2)
        
        # 7-day
        if len(dates) >= 8 and name in history.get(dates[-8], {}):
            old = history[dates[-8]][name]['price']
            if old > 0:
                a['rate_7'] = round((today_info['price'] - old) / old * 100, 2)
        
        # 30-day
        if len(dates) >= 31 and name in history.get(dates[-31], {}):
            old = history[dates[-31]][name]['price']
            if old > 0:
                a['rate_30'] = round((today_info['price'] - old) / old * 100, 2)
        
        alerts.append(a)
    
    print(f'[SM] Alerts: {len(alerts)} items computed')
    return alerts

def generate_recommendations(alerts, items_list=None):
    """Generate recommendations from Steam Market data (with optional BUFF prices)."""
    recs = {'momentum': [], 'oversold': [], 'scarce': [], 'undervalued': [], 'golden_cross': []}
    
    # Build BUFF price lookup from items_list
    buff_lookup = {}
    if items_list:
        for it in items_list:
            n = it.get('name', '')
            if n and it.get('buff_sell', 0) > 0:
                buff_lookup[n] = it
    
    for a in alerts:
        name = a['name']
        price = a['price']
        r1, r7 = a['rate_1'], a['rate_7']
        sl = a.get('sell_listings', 0)
        
        # Momentum: 7d up > 5% and still rising
        if r7 > 5.0 and r1 > 0:
            recs['momentum'].append({
                'name': name, 'price': price,
                'rate_7': r7, 'rate_1': r1,
                'score': min(r7 * 2, 100),
                'reason': f'7-day +{r7:.1f}%, trend up (1-day +{r1:.1f}%)',
            })
        
        # Oversold: 7d down > 8% but has buyers
        if r7 < -8.0 and sl > 10:
            recs['oversold'].append({
                'name': name, 'price': price,
                'rate_7': r7, 'sell_listings': sl,
                'score': min(abs(r7) * 1.5, 100),
                'reason': f'7-day {r7:.1f}% drop, but {sl} listings suggest demand',
            })
        
        # Scarce: very few listings + high price
        if sl < 50 and price >= 100:
            recs['scarce'].append({
                'name': name, 'price': price,
                'sell_listings': sl,
                'score': max(100 - sl, 0),
                'reason': f'Only {sl} listings, high scarcity (price={price:.0f} CNY)',
            })
        
        # Undervalued: BUFF price >> Steam price (no history needed)
        if name in buff_lookup:
            bi = buff_lookup[name]
            buff_sell = bi.get('buff_sell', 0)
            if buff_sell > price > 0:
                premium = round((buff_sell - price) / price * 100, 2)
                if premium > 20:
                    recs['undervalued'].append({
                        'name': name, 'price': price, 'buff_sell': buff_sell,
                        'rate_7': r7, 'premium': premium,
                        'score': min(premium * 2, 100),
                        'reason': f'BUFF ({buff_sell:.0f} CNY) > Steam ({price:.0f} CNY), {premium:.0f}% premium',
                    })
    
    # Sort by score, top 30 each
    for cat in recs:
        recs[cat] = sorted(recs[cat], key=lambda x: x.get('score', 0), reverse=True)[:30]
    
    total = sum(len(v) for v in recs.values())
    cats = ', '.join(f'{k}={len(v)}' for k, v in recs.items())
    print(f'[SM] Recs: {total} total ({cats})')
    return recs

if __name__ == '__main__':
    items = fetch_steam_market_items(max_items=100, min_price=10.0, max_pages=2)
    print(f'Got {len(items)} items')
    if items:
        hp = os.path.join(DATA_DIR, 'market_history.json')
        history = update_market_history(items, hp)
        alerts = compute_alerts_from_history(history)
        recs = generate_recommendations(alerts, items)
        print('=== Recommendations ===')
        for cat, rs in recs.items():
            if rs:
                print(f'\n{cat}:')
                for r in rs[:5]:
                    print(f'  {r["name"]}: {r["price"]:.2f} CNY, score={r["score"]:.0f}')
        print('\nDone.')