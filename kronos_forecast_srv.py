# -*- coding: utf-8 -*-
"""Kronos 批量预测（服务器版，2026-09-26）

与本机版差异：
- 去掉 matplotlib（服务器不画图，省一个依赖）
- KRONOS/DB 默认路径改服务器；REPO=脚本所在目录（读同目录 market.json / ai_recommendations.json）
- 末尾打印内存峰值 PEAK_RSS_MB（供方案 C 可行性评估）

用法（服务器）：
    /home/ubuntu/kronos-venv/bin/python /home/ubuntu/cs2-run/kronos_forecast_srv.py \
        --days 14 --top 10 --samples 3 --out /home/ubuntu/cs2-run/ai_forecast.json
"""
import json
import os
import sqlite3
import sys

KRONOS = os.environ.get('KRONOS_HOME') or '/home/ubuntu/cs2-kronos'
REPO = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get('PRICE_HIST_DB') or '/home/ubuntu/cs2-run/price_history.db'

sys.path.insert(0, KRONOS)
os.chdir(KRONOS)

import pandas as pd  # noqa: E402


def parse_args():
    out = os.path.join(REPO, 'ai_forecast.json')
    days, top, with_vol, samples = 14, 10, False, 3
    a = sys.argv[1:]
    for i, x in enumerate(a):
        if x == '--out' and i + 1 < len(a):
            out = a[i + 1]
        elif x == '--days' and i + 1 < len(a):
            days = int(a[i + 1])
        elif x == '--top' and i + 1 < len(a):
            top = int(a[i + 1])
        elif x == '--withvol':
            with_vol = True
        elif x == '--samples' and i + 1 < len(a):
            samples = int(a[i + 1])
    return out, days, top, with_vol, samples


def daily_ohlc(conn, hn, channel='eco'):
    rows = conn.execute(
        "SELECT substr(ts,1,10) AS day, MIN(price), AVG(price), MAX(price), COUNT(*) "
        "FROM prices WHERE item_name=? AND channel=? GROUP BY day ORDER BY day",
        (hn, channel)).fetchall()
    if len(rows) < 30:
        return None
    df = pd.DataFrame(rows, columns=['timestamps', 'low', 'open', 'high', 'volume'])
    df['close'] = df['open'].shift(-1).fillna(df['open'])
    df['amount'] = df['volume'] * df['close']
    df = df[['timestamps', 'open', 'high', 'low', 'close', 'volume', 'amount']].copy()
    for c in ('open', 'high', 'low', 'close', 'volume', 'amount'):
        df[c] = df[c].astype(float)
    return df


def main():
    out_path, days, top_n, with_vol, samples = parse_args()

    targets = []
    seen = set()
    mkt = json.load(open(os.path.join(REPO, 'market.json'), encoding='utf-8'))
    recs = (mkt.get('recommendations') or {}).get('all') or []
    for i, r in enumerate(recs[:top_n]):
        hn = r.get('hash_name') or ''
        if hn and hn not in seen:
            seen.add(hn)
            targets.append({'hash_name': hn, 'name': r.get('name'), 'rank': i + 1,
                            'source': 'top10', 'score': r.get('score')})
    ai_path = os.path.join(REPO, 'ai_recommendations.json')
    if os.path.exists(ai_path):
        ai = json.load(open(ai_path, encoding='utf-8'))
        for p in ai.get('picks') or []:
            hn = p.get('hash_name') or ''
            if hn and hn not in seen:
                seen.add(hn)
                targets.append({'hash_name': hn, 'name': p.get('name'), 'rank': None,
                                'source': 'ai', 'score': None})
            elif not hn:
                nm = p.get('name')
                for r in recs:
                    if r.get('name') == nm and r.get('hash_name') not in seen:
                        seen.add(r['hash_name'])
                        targets.append({'hash_name': r['hash_name'], 'name': nm, 'rank': None,
                                        'source': 'ai', 'score': r.get('score')})
                        break
    # 持仓：把持仓列表也纳入预测（与 top10/AI精选 去重）
    holdings_path = os.path.join(REPO, 'holdings.json')
    if os.path.exists(holdings_path):
        try:
            ho = json.load(open(holdings_path, encoding='utf-8'))
            for it in (ho.get('items') or []):
                hn = it.get('market_hash') or it.get('hash_name') or ''
                if hn and hn not in seen:
                    seen.add(hn)
                    targets.append({'hash_name': hn, 'name': it.get('name'),
                                    'rank': None, 'source': 'holdings', 'score': None})
        except Exception as e:
            print('  读取持仓失败：%s' % str(e)[:80], flush=True)
    print('目标 %d 件（推荐池前%d + AI精选 + 持仓）' % (len(targets), top_n), flush=True)

    if not targets:
        print('无目标，退出')
        sys.exit(1)

    from src.predictor import CS2SkinPredictor  # noqa: E402
    pred = CS2SkinPredictor(
        model_name=os.path.join(KRONOS, 'hf', 'Kronos-small'),
        tokenizer_name=os.path.join(KRONOS, 'hf', 'Kronos-Tokenizer-base'))
    print('模型已加载', flush=True)

    conn = sqlite3.connect('file:%s?mode=ro' % DB.replace('\\', '/'), uri=True)
    items = []
    for t in targets:
        hn = t['hash_name']
        df = daily_ohlc(conn, hn)
        if df is None:
            print('  跳过（历史<30天）%s' % t.get('name'), flush=True)
            continue
        try:
            _inp = df if with_vol else df[['timestamps', 'open', 'high', 'low', 'close']]
            _acc = None
            for _s in range(max(1, samples)):
                _y = pred.predict(_inp, pred_days=days)
                _vals = _y['close'].astype(float).values
                _acc = _vals if _acc is None else _acc + _vals
            import pandas as _pd
            y = _y.copy()
            y['close'] = _pd.Series(_acc / max(1, samples), index=_y.index)
            cur = float(df['close'].iloc[-1])
            last = float(y['close'].iloc[-1])
            items.append({
                'name': t.get('name'), 'hash_name': hn, 'rank': t.get('rank'),
                'source': t.get('source'), 'score': t.get('score'),
                'history_days': len(df), 'current': round(cur, 2), 'forecast': round(last, 2),
                'change_pct': round((last / cur - 1) * 100, 2),
                'series': [[str(d)[:10], round(float(v), 2)] for d, v in zip(y.index, y['close'])],
            })
            print('  ✓ %-28s %8.2f → %8.2f (%+.1f%%)' % (str(t.get('name'))[:26], cur, last,
                                                         (last / cur - 1) * 100), flush=True)
        except Exception as e:
            print('  ✗ %s: %s' % (t.get('name'), str(e)[:80]), flush=True)
    conn.close()

    out = {'date': __import__('time').strftime('%Y-%m-%d %H:%M'), 'days': days, 'samples': samples,
           'model': 'Kronos-small (服务器 CPU)', 'top_n': top_n, 'n': len(items),
           'source_note': 'Kronos 时序基础模型迁移预测（域外迁移），多次采样取均值，仅作方向参考',
           'items': items}
    json.dump(out, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('\n已写出 %s（%d 件）' % (out_path, len(items)), flush=True)

    try:
        import resource
        _peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        print('PEAK_RSS_MB=%.0f' % (_peak / 1024.0), flush=True)
    except Exception as _e:
        print('PEAK_RSS_MB=NA (%s)' % _e, flush=True)


if __name__ == '__main__':
    main()
