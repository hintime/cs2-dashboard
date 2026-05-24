#!/usr/bin/env python3
"""生成 daily_report.json（日报数据）"""
import json, os, time, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.dirname(os.path.abspath(__file__))

def read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return None

def write_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

def main():
    today = time.strftime('%Y-%m-%d')

    # ── 持仓概况 ──
    holdings = read_json(os.path.join(DATA_DIR, 'holdings.json'))
    items = (holdings or {}).get('items', [])
    total_cost = sum(it.get('cost', 0) for it in items)
    total_value = sum(it.get('price', 0) * it.get('qty', 1) for it in items)
    pnl = total_value - total_cost
    pnl_pct = (pnl / total_cost * 100) if total_cost > 0 else 0

    # 涨跌排行
    top_gainers = []
    top_losers = []
    for it in items:
        r7 = it.get('rate_7', 0) or 0
        if r7 > 0: top_gainers.append({'n': it.get('name', ''), 'r7': r7})
        elif r7 < 0: top_losers.append({'n': it.get('name', ''), 'r7': r7})
    top_gainers = sorted(top_gainers, key=lambda x: -x['r7'])[:5]
    top_losers = sorted(top_losers, key=lambda x: x['r7'])[:5]

    # ── 推荐对比（ECO vs BUFF）─┐
    rec_stats = {'eco': {'count': 0, 'up': 0, 'ret_sum': 0}, 'buff': {'count': 0, 'up': 0, 'ret_sum': 0}}

    try:
        market = read_json(os.path.join(DATA_DIR, 'market.json'))
        recs = []
        src = (market or {}).get('recommendations', {}).get('all', [])
        if isinstance(src, list): recs = src
        if not recs:
            smr = (market or {}).get('steam_market_recs', [])
            if isinstance(smr, list): recs = smr
        for r in recs:
            tag = r.get('tag', 'eco') or 'eco'
            tag = tag if tag in ('eco', 'buff') else 'eco'
            price = r.get('price', 0) or r.get('eco_price', 0) or 0
            eco_price = r.get('eco_price', 0) or 0
            buff_price = r.get('buff_sell', 0) or 0
            ref_price = buff_price if tag == 'buff' else eco_price
            rec_stats[tag]['count'] += 1
            if ref_price > 0 and price > 0:
                ret = (price - ref_price) / ref_price * 100
                rec_stats[tag]['ret_sum'] += ret
                if ret > 0: rec_stats[tag]['up'] += 1
        # 计算百分比
        for tag in ('eco', 'buff'):
            s = rec_stats[tag]
            s['win_rate'] = round(s['up'] / s['count'] * 100, 1) if s['count'] > 0 else 0
            s['avg_ret'] = round(s['ret_sum'] / s['count'], 1) if s['count'] > 0 else 0
    except: pass

    # ── 市场概览 ──
    scan = read_json(os.path.join(DATA_DIR, 'market_scan.json')) or {}
    market_summary = {
        'total': scan.get('total', 0),
        'avg_p': scan.get('avg_p', 0),
        'top_sell': (scan.get('top_sell') or [])[:5]
    }

    # ── 构建日报 ──
    report = {
        'date': today,
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
        'portfolio': {
            'total_cost': round(total_cost, 2),
            'total_value': round(total_value, 2),
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct, 2),
            'count': len(items),
            'top_gainers': top_gainers,
            'top_losers': top_losers
        },
        'recommendations': rec_stats,
        'market': market_summary
    }

    write_json(os.path.join(DATA_DIR, 'daily_report.json'), report)
    print(f'[REPORT] Saved daily report for {today}')

if __name__ == '__main__':
    main()
