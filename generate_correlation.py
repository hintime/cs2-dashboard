"""
Generate correlation_data.json — pre-computed top correlations from price_history.json.
Avoids loading 75MB JSON in browser.
"""
import json, os, time

DATA_DIR = os.path.dirname(os.path.abspath(__file__))

def main():
    t0 = time.time()
    print('[CORR] Loading price_history.json...')
    ph = json.load(open(os.path.join(DATA_DIR, 'price_history.json'), encoding='utf-8'))

    # Extract daily average prices per item (filter excluded)
    exclude_kw = ['Well-Worn', 'Battle-Scarred', '破损不堪', '战痕累累', 'Souvenir',
                  'Music Kit', 'Sticker', '印花', 'Patch', '布章', 'Charm', 'Pin',
                  'Case', 'Container', '武器箱', '胶囊', 'Terminal', 'Graffiti',
                  'Capsule', 'Holo-Foil', 'Confetti', 'Autograph', 'Pass']
    all_dates = {}
    item_prices = {}
    for item, sources in ph.items():
        if any(k in item for k in exclude_kw):
            continue
        eco = sources.get('eco', [])
        if not eco or len(eco) < 20:
            continue
        by_date = {}
        for dp in eco:
            d = dp.get('t', '')[:10]
            if not d: continue
            if d not in by_date: by_date[d] = []
            by_date[d].append(dp.get('p', 0))
        daily = {}
        for d, arr in by_date.items():
            daily[d] = sum(arr) / len(arr)
            all_dates[d] = True
        if len(daily) >= 5:
            item_prices[item] = daily

    date_list = sorted(all_dates.keys())
    print(f'[CORR] {len(item_prices)} items × {len(date_list)} days')

    # Select top items by data coverage
    items = list(item_prices.keys())[:300]

    # Build vectors
    vectors = {}
    for item in items:
        dailies = item_prices[item]
        vec = [dailies.get(d) for d in date_list]
        valid = sum(1 for v in vec if v is not None)
        if valid >= len(date_list) * 0.6:
            vectors[item] = vec

    keys = list(vectors.keys())
    print(f'[CORR] Computing correlations for {len(keys)} items...')

    # Pearson correlation
    pairs = []
    for i in range(len(keys)):
        for j in range(i+1, len(keys)):
            a, b = vectors[keys[i]], vectors[keys[j]]
            n = sx = sy = sxx = syy = sxy = 0
            for k in range(len(a)):
                if a[k] is None or b[k] is None: continue
                n += 1; sx += a[k]; sy += b[k]
                sxx += a[k]*a[k]; syy += b[k]*b[k]; sxy += a[k]*b[k]
            if n < 5: continue
            denom = ((n*sxx - sx*sx) * (n*syy - sy*sy)) ** 0.5
            if denom == 0: continue
            r = (n*sxy - sx*sy) / denom
            if abs(r) > 0.3:
                pairs.append({'a': keys[i], 'b': keys[j], 'r': round(r, 4)})

    pairs.sort(key=lambda x: abs(x['r']), reverse=True)
    pairs = pairs[:200]  # Top 200 strongest correlations

    # Load name map for Chinese display
    try:
        eco = json.load(open(os.path.join(DATA_DIR, 'eco_tracked.json'), encoding='utf-8'))
        name_map = {}
        for it in eco:
            if it.get('HashName') and it.get('GoodsName'):
                name_map[it['HashName']] = it['GoodsName']
    except:
        name_map = {}

    # Build distribution histogram (20 bins from -1 to 1, step 0.1)
    bins = [0] * 20
    for p in pairs:
        bi = int((p['r'] + 1) / 0.1)
        if 0 <= bi < 20:
            bins[bi] += 1

    result = {
        'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'items': len(keys),
        'days': len(date_list),
        'date_range': [date_list[0], date_list[-1]],
        'top_pos': [p for p in pairs if p['r'] > 0][:30],
        'top_neg': [p for p in pairs if p['r'] < 0][:30],
        'distribution': bins,
        'name_map': name_map,
    }

    out_path = os.path.join(DATA_DIR, 'correlation_data.json')
    json.dump(result, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'[CORR] Saved {len(pairs)} pairs ({len(result["top_pos"])} pos, {len(result["top_neg"])} neg) in {time.time()-t0:.1f}s')

if __name__ == '__main__':
    main()
