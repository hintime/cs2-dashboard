# -*- coding: utf-8 -*-
"""推荐战绩记分卡 v2（A）+ 因子有效性（B）+ 大盘基准 —— 只读，不改数据。

v2 相比 v1 新增：
  ● 大盘基准：以「全池同期等权收益」为基准，报告 超额收益 = 推荐均值 − 大盘均值
    （否则分不清「推荐亏钱」还是「整个市场在跌」）
  ● 因子检验改用「推荐理由里的信号」（供给稀缺/买盘/溢价/流动性）——
    因为 channel_eco/channel_buff 字段实测恒为 0、总分又大量堆积在 48.0，两把尺子都失效
产出：outputs/rec_scorecard.json + outputs/rec_outcomes.csv（带标签，供 C/Kronos 复用）
"""
import json, os, sqlite3, statistics, csv, datetime as dt, re
from bisect import bisect_left

REPO = os.environ.get('CS2_REPO') or r'C:\Users\Lenovo\cs2-runner-local'
DB = os.environ.get('PRICE_HIST_DB') or r'E:\cs2-data\price_history.db'
HORIZONS = (7, 14, 30)
TOL_DAYS = 4
SIGNALS = {'稀缺': r'稀缺|仅\d+件|求售比|供\s*[<＜]',
           '买盘/求购': r'买盘|求购|承接|需求强',
           '溢价': r'溢价',
           '流动性': r'流动性|成交'}

def pd_(s):
    return dt.date.fromisoformat(str(s)[:10])

def price_near(dates, pmap, target, tol):
    if not dates:
        return None
    i = bisect_left(dates, target)
    best, bd = None, None
    for j in (i - 1, i, i + 1):
        if 0 <= j < len(dates):
            g = abs((dates[j] - target).days)
            if g <= tol and (bd is None or g < bd):
                bd, best = g, pmap[dates[j]]
    return best

def main():
    conn = sqlite3.connect('file:%s?mode=ro' % DB.replace('\\', '/'), uri=True)
    cur = conn.cursor()
    print('加载全池历史（构建大盘基准）...')
    hists = {}
    for hn, d, p in cur.execute(
            "SELECT item_name, substr(ts,1,10) d, AVG(price) FROM prices "
            "WHERE channel='eco' GROUP BY item_name, d"):
        if p:
            hists.setdefault(hn, []).append((pd_(d), float(p)))
    conn.close()
    pmaps = {hn: {d: p for d, p in v} for hn, v in hists.items()}
    dsorted = {hn: [d for d, _ in v] for hn, v in hists.items()}
    print('池内标的: %d' % len(pmaps))

    def bench(d0, h):
        vs = []
        for hn, dates in dsorted.items():
            en = price_near(dates, pmaps[hn], d0, 3)
            ex = price_near(dates, pmaps[hn], d0 + dt.timedelta(days=h), TOL_DAYS)
            if en and ex:
                vs.append((ex / en - 1) * 100)
        return statistics.mean(vs) if vs else None, len(vs)

    tracks = json.load(open(os.path.join(REPO, 'rec_tracks.json'), encoding='utf-8'))
    recs, skipped = [], 0
    for date_str, items in tracks.items():
        if not isinstance(items, dict):
            continue
        d0 = pd_(date_str)
        for it in items.values():
            if not isinstance(it, dict):
                continue
            hn, entry = it.get('hash_name'), float(it.get('price') or 0)
            if not hn or not entry or hn not in dsorted:
                skipped += 1; continue
            row = {'date': date_str, 'name': it.get('name'), 'hash_name': hn,
                   'score': it.get('score'), 'tag': it.get('tag'), 'entry': entry,
                   'reason': (it.get('reason') or '')}
            for h in HORIZONS:
                ex = price_near(dsorted[hn], pmaps[hn], d0 + dt.timedelta(days=h), TOL_DAYS)
                row['r%d' % h] = round((ex / entry - 1) * 100, 2) if ex else None
            for k, pat in SIGNALS.items():
                row['sig_' + k] = bool(re.search(pat, row['reason']))
            if all(row.get('r%d' % h) is None for h in HORIZONS):
                skipped += 1; continue
            recs.append(row)

    if not recs:
        print('无样本'); return
    dates_all = sorted({r['date'] for r in recs})
    # 大盘基准（按快照日算，再对样本日取平均）
    bmark = {}
    print('计算大盘基准...')
    for h in HORIZONS:
        bv = [bench(pd_(d), h)[0] for d in dates_all]
        bv = [x for x in bv if x is not None]
        bmark[h] = round(statistics.mean(bv), 2) if bv else None

    def agg(rows, key):
        v = [r[key] for r in rows if r.get(key) is not None]
        if not v:
            return None
        return {'n': len(v), 'hit': round(sum(1 for x in v if x > 0) / len(v) * 100, 1),
                'avg': round(statistics.mean(v), 2), 'med': round(statistics.median(v), 2),
                'min': round(min(v), 2), 'max': round(max(v), 2)}

    print('\n=== A. 推荐战绩（样本 %d 条 / %d 天 / %d 标的；跳过 %d）===' % (
        len(recs), len(dates_all), len({r['hash_name'] for r in recs}), skipped))
    print('  %-6s %5s %8s %9s %9s %12s' % ('周期', 'N', '命中率', '均值', '中位', '超额(vs大盘)'))
    for h in HORIZONS:
        a = agg(recs, 'r%d' % h)
        if not a:
            continue
        exc = ('%+.2f%%' % (a['avg'] - bmark[h])) if bmark[h] is not None else '—'
        print('  +%-4d %5d %7.1f%% %+8.2f%% %+8.2f%% %12s   (大盘 %+.2f%%)'
              % (h, a['n'], a['hit'], a['avg'], a['med'], exc, bmark[h] or 0))

    def show(title, groups, key='r14'):
        print('\n' + title)
        print('  %-20s %5s %8s %9s %9s' % ('分组', 'N', '命中率', '均值', '中位'))
        for nm, rows in groups:
            a = agg(rows, key)
            v = rows[0]['__bench__'] if rows and '__bench__' in rows[0] else None
            if not a:
                print('  %-20s %5d %8s' % (nm, len(rows), '—')); continue
            print('  %-20s %5d %7.1f%% %+8.2f%% %+8.2f%%' % (nm, a['n'], a['hit'], a['avg'], a['med']))

    show('按 tag（+14 天）', [(t, [r for r in recs if r.get('tag') == t])
                            for t in sorted({r.get('tag') for r in recs if r.get('tag')})])
    bands = [(0, 40), (40, 47.9), (47.9, 48.1), (48.1, 60), (60, 100)]
    show('按总分固定分档（+14 天）',
         [('%.0f~%.0f' % (lo, hi), [r for r in recs if isinstance(r.get('score'), (int, float)) and lo <= r['score'] <= hi])
          for lo, hi in bands])
    show('按推荐理由信号（+14 天；B：谁是有效因子）',
         [(k, [r for r in recs if r.get('sig_' + k)]) for k in SIGNALS] +
         [('无稀缺信号', [r for r in recs if not r.get('sig_稀缺')])])

    out_dir = os.path.join(REPO, 'outputs'); os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, 'rec_outcomes.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['date', 'name', 'hash_name', 'score', 'tag', 'entry', 'r7', 'r14', 'r30'] +
                   ['sig_' + k for k in SIGNALS])
        for r in recs:
            w.writerow([r['date'], r['name'], r['hash_name'], r['score'], r['tag'], r['entry'],
                        r.get('r7'), r.get('r14'), r.get('r30')] + [r.get('sig_' + k) for k in SIGNALS])
    js = {'generated': dt.datetime.now().strftime('%Y-%m-%d %H:%M'), 'n': len(recs),
          'benchmark': {str(h): bmark[h] for h in HORIZONS},
          'overall': {('r%d' % h): agg(recs, 'r%d' % h) for h in HORIZONS},
          'excess': {('r%d' % h): (round(agg(recs, 'r%d' % h)['avg'] - bmark[h], 2)
                                   if agg(recs, 'r%d' % h) and bmark[h] is not None else None)
                     for h in HORIZONS}}
    json.dump(js, open(os.path.join(out_dir, 'rec_scorecard.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    print('\n产物: outputs/rec_scorecard.json + outputs/rec_outcomes.csv')

if __name__ == '__main__':
    main()
