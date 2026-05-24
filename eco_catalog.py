#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ECO catalog builder
============================
Fetches full ECO catalog (36585 items) and produces two files:

1. eco_catalog.json   – full catalog, all 36585 items
2. eco_tracked.json  – filtered list for the dashboard
                     (Price>=5, SellingTotal>=10, ~12000 items)

Usage:
    python eco_catalog.py           # writes both JSON files
    python -c "import eco_catalog; build()"  # callable
"""
import sys, os, json, time, hashlib
from datetime import datetime

# ── locate cs2-dashboard root ──────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = SCRIPT_DIR  # both files go alongside market.json etc.

sys.path.insert(0, SCRIPT_DIR)
import update   # provides fetch_eco_full, fetch_eco_prices, PARTNER_ID

# ── filters ──────────────────────────────────────────────────────
PRICE_MIN      = 5.0    # ¥5  minimum reference price
SELLING_MIN    = 10     # at least 10 listings
QG_MIN         = 0      # buy-order count (0 = don-t filter)
# Only gloves always kept regardless of filter (user requested no knives / no statrak)
KEEP_CATS      = ('Glove',)
EXCLUDE_CATS   = ('StatTrak', 'Sticker', 'Autograph', 'Pass', 'Patch', 'Graffiti', 'Case', 'MusicKit', 'Charm', 'Other')

def _item_category(item):
    """Return a short category tag."""
    hn = item.get('HashName', '')
    if 'Knife' in hn:
        return 'Knife'
    if any(g in hn for g in ['Gloves', 'Gloves', 'Hand Wraps', 'Sport Gloves',
                                'Specialist Gloves', 'Moto Gloves', 'Driver Gloves', 'Bloodhound Gloves']):
        return 'Glove'
    if hn.startswith('Sticker'):
        return 'Sticker'
    if 'StatTrak' in hn or 'StatTrak' in hn:
        return 'StatTrak'
    if any(c in hn for c in ['Case', 'Container', 'Package']):
        return 'Case'
    if 'Autograph' in hn:
        return 'Autograph'
    # Pass items (Viewer Pass, Operation Pass, Armory Pass, etc.) - not Passion
    if 'Pass' in hn and 'Passion' not in hn:
        return 'Pass'
    # Patch / 布章 - exclude separately from Other
    if 'Patch' in hn or 'Patch' in item.get('GoodsName', ''):
        return 'Patch'
    # Graffiti / 涂鸦
    if 'Graffiti' in hn:
        return 'Graffiti'
    if any(c in hn for c in ['Music Kit']):
        return 'MusicKit'
    if any(c in hn for c in ['Charm', 'Pin']):
        return 'Charm'
    if 'Terminal' in hn:
        return 'Other'
    return 'Weapon'

def _passes_filter(item):
    price    = float(item.get('Price', 0) or 0)
    selling  = int(item.get('SellingTotal', 0) or 0)
    qg       = int(item.get('QGTotal', 0) or 0)
    cat      = _item_category(item)
    if cat in EXCLUDE_CATS:
        return False
    if cat in KEEP_CATS:
        return True
    if price < PRICE_MIN:
        return False
    if selling < SELLING_MIN:
        return False
    if QG_MIN and qg < QG_MIN:
        return False
    # Exclude Battle-Scarred / 战痕累累 / Well-Worn / 破损不堪 / Souvenir(纪念品)
    hn = item.get('HashName', '')
    gn = item.get('GoodsName', '')
    if 'Souvenir' in hn or '纪念品' in gn:
        return False
    if 'Battle-Scarred' in hn or '战痕累累' in gn:
        return False
    if 'Well-Worn' in hn or '破损不堪' in gn:
        return False
    return True

# ── public entry point ──────────────────────────────────────────
def build():
    t0 = time.time()
    print(f'[{datetime.now().strftime("%H:%M:%S")}] ECO catalog builder started')

    # 1. full catalog
    items = update.fetch_eco_full()
    t1 = time.time()
    print(f'  fetch_eco_full : {len(items)} items  ({t1-t0:.1f}s)')

    # 2. attach a stable id for dedup (eco IdNum may be missing for some)
    for it in items:
        hn = it.get('HashName', '')
        it['_id'] = hn  # use HashName as stable id

    # 3. write full catalog (compressed, for search / reference)
    cat_path = os.path.join(DATA_DIR, 'eco_catalog.json')
    with open(cat_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    t2 = time.time()
    print(f'  eco_catalog.json : {len(items)} items  ({t2-t1:.1f}s)')

    # 4. filter for dashboard tracking
    tracked = [it for it in items if _passes_filter(it)]
    t3 = time.time()
    print(f'  filtered         : {len(tracked)} items  ({t3-t2:.1f}s)')
    print(f'    (Price>={PRICE_MIN}, SellingTotal>={SELLING_MIN})')

    # 5. optionally enrich tracked items with BUFF prices via SteamDT
    #    Disabled by default (slow: ~2-3 min for 8198 items with 10 threads)
    #    Enable by setting ENRICH_BUFF=1
    if os.environ.get('ENRICH_BUFF') == '1':
        print('  enriching with BUFF prices (SteamDT, ~2-3 min for 8198 items)...')
        hash_names = [it['HashName'] for it in tracked if it.get('HashName')]
        # Use SteamDT sequential fetcher with rate limiting to avoid API throttle
        buff_prices = update.fetch_steamdt_prices(hash_names, verbose=False)
        if buff_prices and len(buff_prices) > 10:  # 防止API限流时清空已有数据
            for it in tracked:
                hn = it.get('HashName', '')
                if hn in buff_prices:
                    bp = buff_prices[hn]
                    it['buff_sell'] = bp['buff_sell']
                    it['buff_buy'] = bp['buff_buy']
                    it['buff_sell_num'] = bp['buff_sell_num']
                    it['buff_buy_num'] = bp['buff_buy_num']
                    it['buff_source'] = bp.get('buff_source', '')
                    it['platforms'] = bp.get('platforms', {})
            print(f'  BUFF prices enriched for {len(buff_prices)} items')

    # 6. write tracked file
    out_path = os.path.join(DATA_DIR, 'eco_tracked.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(tracked, f, ensure_ascii=False, indent=2)
    t4 = time.time()
    print(f'  eco_tracked.json  : {len(tracked)} items  ({t4-t3:.1f}s)')

    # 7. summary statistics
    prices = [float(it.get('Price',0) or 0) for it in tracked]
    if prices:
        prices.sort()
        n = len(prices)
        print(f'  Price stats (tracked): min={prices[0]:.2f}  median={prices[n//2]:.2f}  max={prices[-1]:.2f}')
        print(f'  P95={prices[int(n*0.95)]:.2f}')

    cats = {}
    for it in tracked:
        c = _item_category(it)
        cats[c] = cats.get(c, 0) + 1
    print('  Category breakdown (tracked):')
    for c, cnt in sorted(cats.items(), key=lambda x: -x[1]):
        print(f'    {c:12s}: {cnt:>6}')

    print(f'[{datetime.now().strftime("%H:%M:%S")}] Done  ({time.time()-t0:.1f}s total)')
    return tracked

if __name__ == '__main__':
    build()
