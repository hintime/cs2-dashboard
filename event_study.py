# -*- coding: utf-8 -*-
"""事件研究：CS2 公告日对饰品市场的真实影响（2026-09-26）

目的：把 AI 的"利好/利空"从观点变成有先验概率的判断。
做法（严格版，不依赖标的映射）：
  1. 事件日 = Steam 公告日（news.json 的 news+updates 去重）
  2. 全市场指数 = 固定标的池（eco 通道，日数≥40）的每日等权收益中位数累积
  3. 事件窗口收益 = 指数在事件日起 n 个交易日的涨跌（n=3/7/14）
  4. 基准 = 全期所有同长度滑动窗口收益分布 → 事件窗口落在哪个分位
输出：event_study.json（供 ai_news_impact prompt 引用真实先验）

局限（如实写入输出）：
  - 贴纸/箱子/刀不在采集池 → 无法做"新箱发布→箱内物品"级研究
  - 公告文本 2026-09-26 起才完整（此前截断 200 字符）→ 关键词级分类受限
  - 事件样本仅 ~11 个，统计功效有限，结论看方向不看小数
"""
import datetime
import json
import os
import sqlite3
import statistics
import time

DB = os.environ.get('PRICE_HIST_DB') or (
    r'E:\cs2-data\price_history.db' if os.name == 'nt' else '/home/ubuntu/cs2-run/price_history.db')
DATA = os.environ.get('CS2_DATA_DIR') or (
    os.path.dirname(os.path.abspath(__file__)) if os.name == 'nt' else '/home/ubuntu/cs2-run')
OUT = os.path.join(DATA, 'event_study.json')
WINDOWS = (3, 7, 14)


def main():
    # ── 1. 事件日 ──
    news = json.load(open(os.path.join(DATA, 'news.json'), encoding='utf-8'))
    ev = {}
    for k in ('news', 'updates'):
        for it in (news.get(k) or []):
            d = it.get('date')
            if not d:
                continue
            ds = datetime.datetime.utcfromtimestamp(int(d)).strftime('%Y-%m-%d')
            ev.setdefault(ds, set()).add(str(it.get('title', ''))[:40])
    events = sorted(ev)
    print('事件日 %d 个: %s' % (len(events), ', '.join(events)))

    # ── 2. 标的池 + 日线 ──
    conn = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    cur = conn.cursor()
    pool = [r[0] for r in cur.execute(
        "SELECT item_name FROM prices WHERE channel='eco' "
        "GROUP BY item_name HAVING COUNT(DISTINCT substr(ts,1,10))>=40")]
    pool_set = set(pool)
    print('标的池 %d 件' % len(pool))

    # 每件物品每日均价
    day_px = {}   # item -> {day: price}
    for item, day, px in cur.execute(
            "SELECT item_name, substr(ts,1,10), AVG(price) FROM prices "
            "WHERE channel='eco' GROUP BY item_name, substr(ts,1,10)"):
        if item in pool_set and px and px > 0:
            day_px.setdefault(item, {})[day] = float(px)
    conn.close()

    days = sorted({d for m in day_px.values() for d in m})
    print('交易日 %d 个: %s -> %s' % (len(days), days[0], days[-1]))
    didx = {d: i for i, d in enumerate(days)}

    # ── 3. 全市场指数：每日等权收益中位数 → 累积 ──
    daily_ret = {}
    for item, m in day_px.items():
        prev = None
        for d in days:
            p = m.get(d)
            if p and prev:
                daily_ret.setdefault(d, []).append(p / prev - 1.0)
            if p:
                prev = p
    idx = {days[0]: 1.0}
    acc = 1.0
    for d in days[1:]:
        rs = daily_ret.get(d) or []
        r = statistics.median(rs) if rs else 0.0
        acc *= (1.0 + r)
        idx[d] = acc
    print('指数构建完成，日收益样本中位 %d 件/日' % statistics.median(
        [len(v) for v in daily_ret.values()] or [0]))

    def win_ret(start_day, n):
        """自 start_day 起 n 个交易日的指数收益（%），不足返回 None"""
        i = didx.get(start_day)
        if i is None:
            # 事件日非交易日 → 取其后第一个交易日
            later = [d for d in days if d >= start_day]
            if not later:
                return None
            i = didx[later[0]]
        j = i + n
        if j >= len(days):
            return None
        return round((idx[days[j]] / idx[days[i]] - 1.0) * 100, 2)

    # ── 4. 基准分布：全期所有同长滑动窗口 ──
    baseline = {}
    for n in WINDOWS:
        vals = []
        for i in range(0, len(days) - n):
            vals.append((idx[days[i + n]] / idx[days[i]] - 1.0) * 100)
        if vals:
            vals.sort()
            baseline[str(n)] = {
                'n_windows': len(vals),
                'mean': round(statistics.mean(vals), 2),
                'median': round(statistics.median(vals), 2),
                'sd': round(statistics.pstdev(vals), 2) if len(vals) > 1 else 0,
                'p10': round(vals[int(len(vals) * 0.10)], 2),
                'p90': round(vals[int(len(vals) * 0.90)], 2),
            }

    # ── 5. 事件窗口 ──
    out_events = []
    for ds in events:
        row = {'date': ds, 'titles': sorted(ev[ds])[:3]}
        for n in WINDOWS:
            row['ret_%dd' % n] = win_ret(ds, n)
        # 7 日窗口在基准分布中的分位
        b7 = baseline.get('7') or {}
        if row.get('ret_7d') is not None and b7:
            lo = b7['mean'] - b7['sd']
            hi = b7['mean'] + b7['sd']
            row['z_7d'] = round((row['ret_7d'] - b7['mean']) / b7['sd'], 2) if b7['sd'] else 0
        out_events.append(row)

    # ── 6. 汇总 ──
    summary = {'n_events': len(events), 'n_pool': len(pool), 'window_days': list(WINDOWS)}
    for n in WINDOWS:
        vs = [e['ret_%dd' % n] for e in out_events if e.get('ret_%dd' % n) is not None]
        if vs:
            b = baseline[str(n)]
            avg = statistics.mean(vs)
            summary['ret_%dd' % n] = {
                'event_mean': round(avg, 2),
                'event_n': len(vs),
                'baseline_mean': b['mean'],
                'diff': round(avg - b['mean'], 2),
                'z_vs_baseline': round((avg - b['mean']) / b['sd'], 2) if b['sd'] else 0,
            }
    # 结论（方向性）
    d7 = (summary.get('ret_7d') or {}).get('z_vs_baseline', 0)
    if abs(d7) < 1.0:
        verdict = ('历史 %d 个公告日后 7 天，全市场表现与随机窗口基本无异（差异 %.2f 个标准差）——'
                   '公告本身对大盘无系统性影响，利好/利空判断应视为弱先验，不构成交易依据。' % (
                       summary['n_events'], d7))
    elif d7 > 0:
        verdict = ('历史 %d 个公告日后 7 天，全市场中位表现高于随机窗口 %.2f 个标准差——'
                   '公告期整体偏强，但仍需结合个券与批次。' % (summary['n_events'], d7))
    else:
        verdict = ('历史 %d 个公告日后 7 天，全市场中位表现低于随机窗口 %.2f 个标准差——'
                   '公告期整体偏弱，警惕利好兑现后的回落。' % (summary['n_events'], d7))
    summary['verdict'] = verdict

    out = {
        'updated': time.strftime('%Y-%m-%d %H:%M'),
        'method': ('全市场指数 = 标的池（eco 通道、日数≥40）每日等权收益中位数的累积；'
                   '事件窗口 = 公告日起 n 个交易日的指数收益；基准 = 全期全部同长度滑动窗口分布'),
        'baseline': baseline,
        'events': out_events,
        'summary': summary,
        'limits': [
            '贴纸/箱子/刀不在采集池 → 无法做「新箱发布→箱内物品」级定向研究',
            '公告正文 2026-09-26 起才完整抓取（此前截断 200 字符）',
            '事件样本仅 %d 个，统计功效有限，结论看方向不看小数' % len(events),
            '事件窗口为全市场口径（非个券），个券影响需另做映射',
        ],
    }
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('已写出 %s' % OUT)
    print('--- 汇总 ---')
    for n in WINDOWS:
        s = summary.get('ret_%dd' % n)
        if s:
            print('  %2d日: 事件均值 %+.2f%% vs 基准 %+.2f%% (差 %+.2f, z=%+.2f, n=%d)' % (
                n, s['event_mean'], s['baseline_mean'], s['diff'], s['z_vs_baseline'], s['event_n']))
    print('  结论:', verdict)


if __name__ == '__main__':
    main()
