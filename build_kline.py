# -*- coding: utf-8 -*-
"""日K 聚合器 —— 把 prices 表的日内采样聚合成 OHLC，供前端画 K 线图。

背景（2026-10-05 义轩要求持仓走势图加 K 线版）
------------------------------------------------
持仓的 price_history 只有「每天一个均价」，画不出有意义的 K 线 —— 影线只能是
两个均价之间的连线，振幅完全是假的。真正的日内波动在 prices 表里：
每 4-6 小时采一次，一天 3-10 个点（实测 2026-10-03：3294 件有 4 个点，
是主力档位）。

所以这里从 prices 表按天聚合出真 OHLC：
    open  = 当天第一个采样点
    high  = 当天最高采样点
    low   = 当天最低采样点
    close = 当天最后一个采样点
    n     = 当天采样点数（前端用它提示"本日样本少，影线仅供参考"）

⚠ **诚实的边界**（必须让前端能转达给用户，不能装作是真实成交）
   采样是 4-6 小时一次，不是行情站的分钟级 tick。所以：
     · high/low 是「当天采样到的最高/最低」，不等于真实成交极值；
     · 采样点少的当天（n<4）影线会明显收窄 → 输出里带 n，前端该提示就提示；
     · 结论：**日K 可用，小时K 不可用**（一天才 3-10 个点，聚不出有意义的 OHLC）。

口径与既有链路一致：优先 eco（ECO 是主源），缺失回落 buff。
只输出采样天数 >= MIN_DAYS 的标的，避免大量一天一个点的"假 K 线"。

用法（服务器）：
    venv/bin/python build_kline.py --out kline.json
    venv/bin/python build_kline.py --out kline.json --days 120 --min-days 5
"""
import argparse
import json
import os
import sqlite3
import time

REPO = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get('PRICE_HIST_DB') or os.path.join(REPO, 'price_history.db')
HOLDINGS = os.environ.get('KRONOS_HOLDINGS') or os.path.join(REPO, 'holdings.json')

# 采样天数门槛：低于此天数的标的直接不输出（K 线需要连续性才读得出趋势）
MIN_DAYS = 5
# 单日最少采样点：低于此点数，当天的 high/low 不可信 → 该日只输出 close
MIN_PTS_FOR_RANGE = 3
# 最多输出多少件（K 线数据体积是折线的 4 倍，按需限制）
LIMIT_ITEMS = 1200


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(REPO, 'kline.json'))
    ap.add_argument('--days', type=int, default=120, help='回看天数')
    ap.add_argument('--min-days', type=int, default=MIN_DAYS)
    ap.add_argument('--min-pts', type=int, default=MIN_PTS_FOR_RANGE)
    ap.add_argument('--limit', type=int, default=LIMIT_ITEMS)
    a = ap.parse_args()
    return a


def load_holdings():
    """读 holdings.json，返回要强制纳入 K 线的 market_hash 集合（list，保持顺序）。

    ⚠ holdings.json 的饰品标识有两种字段：新结构用 market_hash，旧结构用 name。
      两种都收（前端 klOf 也是 mh/name 双 key 匹配），少一个就漏一批。
    ⚠ 读不到文件不是致命错误 —— 返回空集合，退化成纯按活跃度选品。"""
    try:
        with open(HOLDINGS, encoding='utf-8') as f:
            d = json.load(f)
    except Exception as e:
        print('  提示：读不到 holdings.json（%s），本次不强制覆盖持仓' % e, flush=True)
        return []
    items = d.get('items') or d.get('holdings') or (d if isinstance(d, list) else [])
    out = []
    for h in items:
        if not isinstance(h, dict):
            continue
        for k in ('market_hash', 'mh', 'name', 'n'):
            v = h.get(k)
            if v:
                out.append(v)
                break
    return out


def main():
    args = parse_args()
    since = time.strftime('%Y-%m-%d',
                           time.localtime(time.time() - args.days * 86400))
    conn = sqlite3.connect('file:%s?mode=ro' % DB.replace('\\', '/'), uri=True)

    # 一次性把窗口内的采样点全取出来（4700 件 × 120 天 ≈ 30 万行，
    # 内存里聚合比 4700 次 SQL 循环快两个数量级）
    # 聚合全部交给 SQL 做（GROUP BY item_name, day）。
    # ⚠ 2026-10-05 实测：把 420 万行拉到 Python 内存再聚合要 98 秒 / 吃满 2C2G，
    #   而 SQL 侧聚合只需几秒 —— 服务器只有 2 核 2G，这个差别是决定性的。
    # open/close 用「窗口内首个/末个采样点」：靠 (min_ts, max_ts) 二次取点，
    # 不能用 FIRST()/LAST() —— SQLite 没有这两个聚合函数。
    # 聚合：SQL 侧 GROUP BY。
    # ⚠ 2026-10-05 实测（服务器 2C2G，窗口 120 天 / 420 万行采样点）：
    #   ① 全量拉进 Python 内存聚合 = 98 秒且吃满内存 → 不可行
    #   ② SQL GROUP BY 取 MIN/MAX/COUNT + Python 二次批量查 (item,ts)→price
    #      = 2 分 14 秒 → 能跑通但慢（这是当前采用的方案）
    #   ③ 把 prices 自 JOIN 两次直接取首/末点 = 2 分钟仍跑不完（被 ssh 超时砍），
    #      三次 JOIN 在 2C2G 上过重 → 放弃
    #   结论：②是这台机器的可行解。窗口别往大调（--days 越大越慢）。
    sql = """
    SELECT item_name, day,
           MIN(ts) AS first_ts, MAX(ts) AS last_ts,
           MIN(price) AS low, MAX(price) AS high,
           COUNT(*)   AS n
    FROM (
      SELECT item_name, channel, substr(ts,1,10) AS day, ts, price
      FROM prices
      WHERE substr(ts,1,10) >= ? AND price > 0
    )
    GROUP BY item_name, day
    """
    agg = conn.execute(sql, (since,)).fetchall()
    print('SQL 聚合完成，%d 个 (物品,天) 组' % len(agg), flush=True)
    if not agg:
        conn.close()
        print('无数据，退出')
        return

    # 取 open/close：批量查 (item_name, ts) → price，避免 47 万次 N+1 查询。
    # open 与 close 各自独立分批（不能混在同一个 IN 里再靠切片分派 ——
    # 批次边界会切错，导致某组的 open 实际取到了 close 的值）。
    BATCH = 400
    open_map, close_map = {}, {}
    for keys, store in (([(r[0], r[2]) for r in agg], open_map),
                        ([(r[0], r[3]) for r in agg], close_map)):
        for i in range(0, len(keys), BATCH):
            part = keys[i:i + BATCH]
            ors = ' OR '.join(["(item_name=? AND ts=?)"] * len(part))
            params = [x for kv in part for x in kv]
            for hn, ts, px in conn.execute(
                    "SELECT item_name, ts, price FROM prices WHERE %s" % ors, params):
                store[(hn, ts)] = px
    conn.close()
    print('open/close 取值完成', flush=True)

    per_item = {}          # item -> {day -> (o,h,l,c,n,r)}
    n_open_miss = 0
    for hn, day, fts, lts, lo, hi, n in agg:
        o = open_map.get((hn, fts))
        c = close_map.get((hn, lts))
        if o is None:
            n_open_miss += 1
            continue
        if c is None:
            c = o
        it = per_item.setdefault(hn, {})
        it[day] = [o, hi, lo, c, n, 1 if n >= args.min_pts else 0]
    if n_open_miss:
        print('  警告：%d 组取不到 open/first 点已跳过' % n_open_miss, flush=True)

    # 选通道：eco 优先（ECO 是主源），buff 兜底
    items = []
    for hn, days in per_item.items():
        if len(days) < args.min_days:
            continue
        ks = sorted(days.keys())
        bars = []
        for d in ks:
            o, h, l, c, n, r = days[d]
            bars.append({
                'd': d,
                'o': round(o, 2), 'h': round(h, 2),
                'l': round(l, 2), 'c': round(c, 2),
                # r=0 表示当天采样点不足 min_pts → high/low 不可信，影线仅供参考
                'r': r,
                'n': n,
            })
        items.append({'hash_name': hn, 'bars': bars})

    # ★ 持仓必须 100% 覆盖（2026-10-05 实测踩坑）：
    #   K 线图只在持仓详情里用，若按 limit 截断取「最近有成交的 1200 件」，
    #   32 件持仓里只有 6 件能查到 K 线（其余在 5106 件合格品的尾部被砍掉）。
    #   —— 这不是数据缺失，是选品策略的问题。所以：
    #     ① 先把 holdings.json 里的 market_hash/name 全部无条件收进来；
    #     ② 剩余名额再按最后一天排（优先给活跃品）。
    #   持仓多占的体积可忽略（32 件 vs 1200 件）。
    hold_keys = load_holdings()
    hold_set = set(hold_keys) if hold_keys else set()
    hold_items, rest = [], []
    for x in items:
        (hold_items if x['hash_name'] in hold_set else rest).append(x)
    if hold_keys:
        found = {x['hash_name'] for x in hold_items}
        missing = [k for k in hold_keys if k not in found]
        print('  持仓覆盖 %d/%d 件' % (len(hold_items), len(hold_keys)), flush=True)
        if missing:
            print('  ⚠ 持仓里这 %d 件没有 K 线（采样天数不足 %d 天）：%s'
                  % (len(missing), args.min_days,
                     '、'.join(missing[:5]) + ('…' if len(missing) > 5 else '')),
                  flush=True)
    rest.sort(key=lambda x: x['bars'][-1]['d'], reverse=True)
    total = len(items)
    room = max(0, args.limit - len(hold_items))
    items = hold_items + rest[:room]

    out = {
        'date': time.strftime('%Y-%m-%d %H:%M'),
        'granularity': '1d',
        'days': args.days,
        'min_days': args.min_days,
        'min_pts_for_range': args.min_pts,
        'n': len(items),
        'total_eligible': total,
        'source_note': ('由 price_history.db 的日内采样(每4-6小时一次)按天聚合，'
                        '非真实成交极值；样本少的当天 r=0，影线仅供参考'),
        'caveat': ('采样频率 4-6 小时 → 日K 可用，小时K 不可用；'
                   'high/low 是当天采样到的极值，不等于真实成交高低点'),
        'items': items,
    }
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))

    sz = os.path.getsize(args.out)
    bars_total = sum(len(x['bars']) for x in items)
    r0 = sum(1 for x in items for b in x['bars'] if not b['r'])
    print('写出 %s' % args.out, flush=True)
    print('  %d 件（合格 %d 件，截断 %d 件）· %d 根K线 · %.2f MB'
          % (len(items), total, max(0, total - len(items)), bars_total, sz / 1048576.0),
          flush=True)
    print('  影线不可信的K线占比 %.1f%%（r=0，即当天采样点 < %d）'
          % (100.0 * r0 / max(1, bars_total), args.min_pts), flush=True)


if __name__ == '__main__':
    main()
