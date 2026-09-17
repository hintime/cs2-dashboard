# -*- coding: utf-8 -*-
"""Kronos 批量预测：只预测「推荐池前 N 名」+「AI 精选」的标的

用法:
    venv\\Scripts\\python.exe forecast_batch.py [--out <json路径>] [--days 14] [--top 10]

输出 ai_forecast.json:
    {date, days, model, source_note, items:[{name, hash_name, rank, source,
     current, forecast, change_pct, series:[[day, close], ...]}]}

注意（务必保留）：
- 必须在剥掉 WorkBuddy `PYTHONPATH` 注入的环境里运行（否则 matplotlib 建字体缓存会被批量删除守卫拦下）。
- Kronos 是在全球交易所 K 线上预训练的，皮肤价格属域外迁移，单次采样有随机性
  （同一标的两次可差 ~0.4pp），只作辅助方向参考，不作买卖依据。
"""
import json
import os
import sqlite3
import sys

import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS']
matplotlib.rcParams['axes.unicode_minus'] = False

KRONOS = os.environ.get('KRONOS_HOME') or r'C:\Users\Lenovo\cs2-kronos'
REPO = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(REPO, 'price_history.db')

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

    # ── 1. 目标清单：推荐池前 N + AI 精选（按 hash_name 去重）──
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
                # AI 精选可能只有中文名 → 用名字反查推荐池
                nm = p.get('name')
                for r in recs:
                    if r.get('name') == nm and r.get('hash_name') not in seen:
                        seen.add(r['hash_name'])
                        targets.append({'hash_name': r['hash_name'], 'name': nm, 'rank': None,
                                        'source': 'ai', 'score': r.get('score')})
                        break
    print('目标 %d 件（推荐池前%d + AI精选）' % (len(targets), top_n), flush=True)

    if not targets:
        print('无目标，退出'); sys.exit(1)

    # ── 2. 加载模型（只加载一次）──
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
            # 默认只喂 OHLC。实测把「当天采样次数」当 volume/amount 喂进去会严重污染模型：
            # A/B → 带量 11/11 看跌、均值 -13.8%、最差 -41.6%；仅 OHLC 均值 -2.1%、有涨有跌。
            _inp = df if with_vol else df[['timestamps', 'open', 'high', 'low', 'close']]
            # 多次采样取均值：单次采样随机性很大（同一标的两次可差数个百分点）
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
           'model': 'Kronos-small (本地 CPU)', 'top_n': top_n, 'n': len(items),
           'source_note': 'Kronos 时序基础模型迁移预测（域外迁移），多次采样取均值，仅作方向参考',
           'items': items}
    json.dump(out, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('\n已写出 %s（%d 件）' % (out_path, len(items)), flush=True)


if __name__ == '__main__':
    main()
