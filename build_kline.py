# -*- coding: utf-8 -*-
"""K 线聚合器 —— 三档粒度（2小时K / 日K / 周K），从 price_history.db 聚合 OHLC。

三个输出文件（各管一件事，口径写在文件头里）
----------------------------------------------
  kline_2h.json  2小时K  近 14 天  桶内首个/末个采样 + 桶内极值
  kline_1d.json  日K    全量历史   一天一根
  kline_1w.json  周K    全量历史   一周一根

★ 无上限（2026-10-06 义轩要求）
  日K / 周K **不再有--days 上限**，回溯到数据库里最早的一天为止。
  数据只增不减（price_history.db 已设 PRICE_HIST_KEEP_DAYS=0 永不自动删），
  所以「历史越久 → K 线越长」是自动发生的，不需要改配置。
  仅 2小时K 保留窗口（14 天）：小粒度数据量大，只保留近期（实测 200 件 14 天约 5MB）。

⚠ 采样口径（2026-10-06 服务器实测校正，**推翻了 10-05 的错误结论**）
----------------------------------------------------------------------
  10-05 我在注释里写「一天 28 个采样点，摊到 24 小时 = 每小时 1.2 个点，
  小时K 不可用」。**这个结论是错的**，而且错了两次：

  错误 1（10-05）：把「跨全部饰品的 28 个时点」当成了「单件每天的点」，
    再除以 24 小时 → 每小时 1.2 个。实际上那 28 个是**全局**时点，
    单件在自己的每个小时里都有采样。
    实测：采样覆盖 **24 小时全覆盖**，单件每小时 2-3 个点。

  错误 2（10-06 第一版）：修成「1 小时粒度」后，发现 **96.1% 的 1 小时桶
    只有 1 个点** → open=high=low=close，影线完全退化，画出来是一堆竖线。
    根因：采样集中在每个整点的前几分钟（cron `*/30` 的 prices 轮实际都落在 :15），
    不是均匀铺在小时内。
    实测 2 小时桶：1 点 35.4% / 2-3 点 64.1% / 4+ 点 0.5% —— 影线真正有信息量。
    → **最小粒度定为 2 小时**，这是数据决定的，不是偷懒。

    单件在自己的每个小时里都有 2-3 个点（多平台各采一次）。

  所以 **2小时K / 日K / 周K 三档全部可用**（最小粒度 2 小时，见上）。

⚠ 采集密度在 9/20 有一次跃升（2026-10-06 实测，决定 q 分级的依据）
-----------------------------------------------------------------------
  **注意这里有个坑，我自己也踩了**：先测到「单件每天 eco 点数 7-08~9-19 是
  3~18个、9-20~10-06 是 57~91 个」，就照这个设了 q 阈值(40/12)，
  结果 94% 的 K 线被判「稀疏」。后来发现 57~91 是**全表按天**（含三个渠道混算），
  不是「单件在优先渠道内的点数」。分渠道后实测（近 6 天 / 28441 样本）：

    1 点 0.5%   2-3 点 13.9%   4-11 点 73.3%   12-39 点 12.3%   40+ 点 0%
    max=28   平均 6.3

  即：**日桶的常态就是 4~11 个点**（一天的 24 小时里，优先渠道每小时采 1 次）。
  所以 q 阈值必须落在这个区间才有区分度。
  另外历史段（7-08~9-19）确实比现在稀疏 4 倍左右，q 分级正好用来在
  界面上如实区分 —— **数据一条不丢**，稀疏的历史照样有趋势价值，
  只是高低点不能当极值使；砍掉才是真丢信息。

⚠ 跨平台价差会造假振幅（2026-10-06 实测发现的既存 bug，本次一并修掉）
------------------------------------------------------------------
  同一时刻同一件饰品，三个平台各采一次：
      2026-10-01T10:15:09  buff=22.75   eco=23.10   yy=22.99
      2026-10-01T10:59:28  buff=22.73   eco=23.10   yy=22.00
  这不是价格波动，是**三个市场的正常价差**。原代码 SQL 里 SELECT 了 channel
  却从没在聚合里用它（`GROUP BY item_name, day`），于是：
      混聚合 10-01 日K → h=23.17  l=21.90  振幅 5.8%
      分平台 buff  →   h=23.17  l=21.90  （yy 拖低了低点）
      分平台 eco   →   h=23.10  l=22.70  振幅 1.7%
  混平台的影线把**平台价差当成了日内波动**，画出来的 K 线振幅是假的。
  修法：按 (物品, 桶, 渠道) 先各自聚合，再**按渠道优先级取一条**（eco > buff > yy），
  高低只在该渠道内部取。渠道优先级与全站既有口径一致（ECO 是主源）。

性能（服务器 2 核 2G，实测）
----------------------------
  聚合全部交给 SQL（窗口函数 + GROUP BY），Python 只做结果整形。
  日K 全量 58 天 / 451 万行 / 5189 件 ≈ 数秒~十几秒，可接受。
  ⚠ 不要为了「稳」把全表拉到 Python 内存再聚合 —— 10-05 实测那样要
    98 秒且吃满 2C2G，会把并行的 Kronos 推理挤死。

用法（服务器）：
    venv/bin/python build_kline.py                    # 三档全建
    venv/bin/python build_kline.py --only 1d          # 只建日K
    venv/bin/python build_kline.py --days 30          # 小时K 窗口（默认 7）
    venv/bin/python build_kline.py --limit-items 1500  # 限制件数
    venv/bin/python build_kline.py --no-push          # 只落盘不推
"""
import argparse
import datetime
import hashlib
import json
import os
import sqlite3
import sys
import time

REPO = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get('PRICE_HIST_DB') or os.path.join(REPO, 'price_history.db')
HOLDINGS = os.environ.get('KRONOS_HOLDINGS') or os.path.join(REPO, 'holdings.json')

# 采样天数门槛：低于此天数的标的直接不输出（K线需要连续性才读得出趋势）
MIN_DAYS = 5
# 各档的「桶内最少采样点」门槛 —— 必须按粒度区分，用同一个值会全盘标不可信。
#
# ⚠ 2026-10-06 实测踩过两次坑：
#   ① 起点用 min_pts=3 套到小时K → 「影线弱 99.6%」。小时桶本来只有 1-3 个点
#      （每小时采一次 × 优先渠道），3 的门槛把一半以上的桶全判死。
#   ② 改小后忘了日/周桶也不该用 3 —— 分渠道实测日桶常态是 4~11 个点
#      （见 Q_THRESH 处注释），用 3 做门槛几乎等于没门槛。
# 现按实测分布定：2小时 2 / 日 4 / 周 25。
MIN_PTS_BY_GRAN = {'2h': 2, '1d': 4, '1w': 25}
MIN_PTS_FOR_RANGE = 3      # 仅当命令行显式传 --min-pts 时覆盖上面三项
# 密度分级 q 的门槛（bar.q）：0稀疏 / 1一般 / 2充足。
#
# ⚠ 2026-10-06 实测校准（第一版阈值拍错了，也是靠实测纠出来的）：
#   我最初按「单件每天 57~91 个点」设 q 门槛（40/12）→ 结果 94% 的K线被判稀疏。
#   错在：57~91 是**全表按天**的件数（含 buff+yy+eco 三个渠道混算），
#   不是「单件在优先渠道内的点数」。分渠道后实测（近 6 天 / 28441 个样本）：
#       1 点 0.5%   2-3 点 13.9%   4-11 点 73.3%   12-39 点 12.3%   40+ 点 0%
#       max=28  平均 6.3
#   所以日桶的常态是 4~11 个点，阈值必须落在这个区间里才有区分度。
#   现按各档实测的量级分别设定（见 Q_THRESH）。
Q_THRESH = {'2h': (2, 4), '1d': (4, 12), '1w': (25, 60)}
# 各档默认输出件数上限（K 线数据体积是折线的 4 倍，按需限制）
LIMIT_2H = 200      # 2小时K 单件 14 天约 25KB → 200 件约 5MB
LIMIT_1D = 1200     # 日K 单件 65 字节/天 → 1200 件 × 58 天 约 4.5MB
LIMIT_1W = 3000     # 周K 单件 65 字节/周 → 全量 5189 件也才 0.64MB
# 2小时K 回看窗口（天）。小粒度数据量大，只保留近 N 天。
HOURS_WINDOW_DAYS = 14
# 渠道优先级：数字小的优先。高低只在优先渠道内部取，避免平台价差污染振幅。
CHANNEL_PRIORITY = ('eco', 'buff', 'yy')
MIN_HOURS_FOR_2H = 30   # 2小时K 最少要有这么多个 2 小时桶才输出（否则影线太稀）

OUT_FILES = {'2h': 'kline_2h.json', '1d': 'kline_1d.json', '1w': 'kline_1w.json'}


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', choices=list(OUT_FILES),
                    help='只建某一档；不给则三档全建')
    ap.add_argument('--out-dir', default=REPO)
    ap.add_argument('--days', type=int, default=HOURS_WINDOW_DAYS,
                    help='2小时K 回看天数（仅 --only 2h 时用；日K/周K 无上限）')
    ap.add_argument('--min-days', type=int, default=MIN_DAYS)
    ap.add_argument('--min-pts', type=int, default=0,
                    help='覆盖各档的桶内最少采样点门槛；0 = 用 MIN_PTS_BY_GRAN')
    ap.add_argument('--min-hours', type=int, default=MIN_HOURS_FOR_2H)
    ap.add_argument('--limit-items', type=int, default=0,
                    help='覆盖各档默认件数上限；0 = 用默认')
    ap.add_argument('--no-push', action='store_true', help='只落盘不推 GitHub')
    return ap.parse_args()


def load_holdings():
    """读 holdings.json，返回要强制纳入 K 线的标识集合（list，保持顺序）。

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


# ── 桶键表达式 ──────────────────────────────────────────────────────────────
#   2h → 'YYYY-MM-DDTHH'   2 小时（起点 00/02/04…）
#   1d → 'YYYY-MM-DD'      日
#   1w → 'YYYY-MM-DD'      自然周的**周一日期**（直接让 SQL 算，不在 Python 换算）
#
# ⚠ 周K 别用 strftime('%Y-W%W')（2026-10-06 实测踩过）：
#   %W 的周起始规则和 ISO 不一致，换算出来最后一根只到 09-28，
#   而库里明明有 10-04/10-06 的数据 → **周K 会少掉最近一周，且没有任何报错**。
#   正确写法 date(ts, 'weekday 0', '-6 days')：'weekday 0' 前进到本周日，
#   再退 6 天 → 回到本周一。实测末根 = 2026-10-05，覆盖到 10-06 ✔
#
# ⚠ 最小粒度为什么是 2 小时而不是 1 小时（2026-10-06 实测）：
#   采样集中在每个整点的前几分钟（cron `*/30` 的 prices 轮实际都落在 :15），
#   所以「1 小时桶」里96.1% 只有 1 个点 → open=high=low=close，影线完全退化，
#   画出来的「小时K」是一堆竖线，实质上只是折线。
#   2 小时桶实测：1 点 35.4% / 2-3 点 64.1% / 4+ 点 0.5% —— 影线真正有信息量。
#   所以最小粒度定为 2 小时，文件名kline_2h.json，界面上标「2小时K」。
#   ⚠ 这里的取舍是数据决定的，不是偷懒：1 小时粒度在当前采集节奏下拿不到 OHLC。
BUCKET_SQL = {
    '2h': "substr(ts,1,10) || 'T' || printf('%02d', CAST(strftime('%H', ts) AS INTEGER) / 2)",
    '1d': "substr(ts,1,10)",                                  # 2026-10-05
    '1w': "date(ts, 'weekday 0', '-6 days')",                 # 2026-10-05（周一）
}
GRAN_LABEL = {'2h': '2小时K', '1d': '日K', '1w': '周K'}
GRAN_FILE = {'2h': 'kline_2h.json', '1d': 'kline_1d.json', '1w': 'kline_1w.json'}


def fetch_buckets(conn, gran, since, min_pts):
    """按 (物品, 桶, 渠道) 聚合，再按渠道优先级为每个 (物品,桶) 选一条。

    ★ 这是修「平台价差污染振幅」的核心：原来 GROUP BY item,day 把三个平台
      混在一起取 MIN/MAX，等于把 eco 与 yy 的价差当成日内波动。
      现在先分渠道各自聚合，再用 ROW_NUMBER 按 CHANNEL_PRIORITY 选一条，
      high/low 只在该渠道内部产生。
    ⚠ 用窗口函数而不是「取完再在 Python 里挑」：后者要把全部明细拉进内存，
      10-05 实测那样 451 万行要 98 秒且吃满 2G 内存。

    返回 [(item, bucket, channel, first_ts, last_ts, lo, hi, n), ...]
    """
    bsql = BUCKET_SQL[gran]
    prio = ' '.join(
        "WHEN '%s' THEN %d" % (ch, i) for i, ch in enumerate(CHANNEL_PRIORITY))
    sql = """
    WITH per_ch AS (
      SELECT item_name, channel, %s AS bucket,
             MIN(ts) AS first_ts, MAX(ts) AS last_ts,
             MIN(price) AS lo, MAX(price) AS hi,
             COUNT(*)   AS n
      FROM (
        SELECT item_name, channel, ts, price
        FROM prices
        WHERE %s AND price > 0
      )
      GROUP BY item_name, channel, bucket
    ),
    ranked AS (
      SELECT item_name, bucket, channel, first_ts, last_ts, lo, hi, n,
             ROW_NUMBER() OVER (
               PARTITION BY item_name, bucket
               ORDER BY CASE channel %s ELSE 99 END, n DESC
             ) AS rn
      FROM per_ch
    )
    SELECT item_name, bucket, channel, first_ts, last_ts, lo, hi, n
    FROM ranked WHERE rn = 1
    """ % (bsql, ('substr(ts,1,10) >= ?' if since else '1=1'), prio)
    return conn.execute(sql, ((since,) if since else ())).fetchall()


def fetch_open_close(conn, rows):
    """取每个 (物品, first_ts, channel) 与 (物品, last_ts, channel) 的真实价格。

    ⚠ 必须带 channel 条件：同一时刻同一件有三个平台的价格，
      只按 (item, ts) 查会返回三行，SQLite 只取第一行 → 拿到的是任意一个平台，
      与 high/low 所用的渠道不一致 → open/close 和影线对不上。
    ⚠ 字典键必须含 ts：(item, channel) 作键会让同一件的所有桶互相覆盖
      （同一天只有一个 first_ts，但跨天有多个 first_ts）→ 全部桶只留最后一条。
      键用 (item, ts, channel) 才唯一。
    ⚠ SQL 占位符顺序与参数顺序必须一致：写成 (item_name=? AND ts=? AND channel=?)
      就必须按 (item, ts, channel) 展开参数。早先写成 keys=(item, channel, ts)
      而 SQL 是 (item, ts, channel) → 参数错位 → 查询全空 → 27 万组全部 miss。
    分批（OR 条件）避免 SQL 变量超限（SQLITE_MAX_VARIABLE_NUMBER）。
    """
    BATCH = 300
    open_map, close_map = {}, {}
    # keys 一律按 (item, ts, channel) 排 —— 与下面 SQL 的占位符顺序严格一致
    for keys, store in (([(r[0], r[3], r[2]) for r in rows], open_map),
                        ([(r[0], r[4], r[2]) for r in rows], close_map)):
        for i in range(0, len(keys), BATCH):
            part = keys[i:i + BATCH]
            ors = ' OR '.join(["(item_name=? AND ts=? AND channel=?)"] * len(part))
            params = [x for kv in part for x in kv]
            for hn, ts, ch, px in conn.execute(
                    "SELECT item_name, ts, channel, price FROM prices WHERE %s" % ors,
                    params):
                store[(hn, ts, ch)] = px
    return open_map, close_map


def build_gran(conn, gran, since, min_days, min_pts, min_hours, limit):
    """构建一档 K 线，返回 (items, meta_dict)。

    min_pts<=0 时用 MIN_PTS_BY_GRAN[gran]（按粒度区分，见常量处注释）。
    """
    if min_pts <= 0:
        min_pts = MIN_PTS_BY_GRAN.get(gran, MIN_PTS_FOR_RANGE)
    q_lo, q_hi = Q_THRESH.get(gran, (12, 40))
    t0 = time.time()
    rows = fetch_buckets(conn, gran, since, min_pts)
    print('  [%s] 分渠道聚合 %d 个 (物品,桶) 组，%.1fs'
          % (gran, len(rows), time.time() - t0), flush=True)
    if not rows:
        return [], {}

    open_map, close_map = fetch_open_close(conn, rows)
    print('  [%s] open/close 取值完成' % gran, flush=True)

    per_item = {}
    n_miss = 0
    for hn, bucket, ch, fts, lts, lo, hi, n in rows:
        # 三档的桶键都是前端能直接 Date.parse 的格式（1h 补 :00）
        key = bucket + ':00' if gran == '2h' else bucket
        o = open_map.get((hn, fts, ch))
        c = close_map.get((hn, lts, ch))
        if o is None or c is None:
            n_miss += 1
            continue
        per_item.setdefault(hn, {})[key] = (o, hi, lo, c, n)
    if n_miss:
        print('  ⚠ [%s] %d 组取不到 open/close 已跳过' % (gran, n_miss), flush=True)

    items = []
    for hn, buckets in per_item.items():
        ks = sorted(buckets.keys())
        # 天数门槛：小时K 折算成「覆盖天数」（有 ≥min_hours 个小时桶才算一天）
        if gran == '2h':
            days = len({k[:10] for k in ks})
            if len(ks) < min_hours or days < min_days:
                continue
        else:
            if len(ks) < min_days:
                continue
        bars = []
        for k in ks:
            o, h, l, c, n = buckets[k]
            bars.append({
                'd': k,
                'o': round(o, 2), 'h': round(h, 2),
                'l': round(l, 2), 'c': round(c, 2),
                'r': 1 if n >= min_pts else 0,   # 0 = 桶内采样点不足，影线仅供参考
                'n': n,
                # q=密度分级（2026-10-06 加）：
                #   采集密度在 9/20 出现过一次跃升 —— 实测单件每天 eco 采样点
                #   9-19 及以前只有 3~18 个（还有整天断档），9-20 起变成 57~91 个。
                #   同样「≥min_pts」的两根 K 线，质量可能差 4 倍：
                #     n=3  → 只有 1 小时左右覆盖，高低是运气
                #     n=70 → 覆盖一整天，高低有代表性
                #   所以前端按 q 分三档给不同的影线样式 + 提示，
                #   而不是笼统地只分「可靠/不可靠」。数据全部保留，不因稀疏而丢。
                'q': 2 if n >= q_hi else (1 if n >= q_lo else 0),
            })
        items.append({'hash_name': hn, 'bars': bars})

    # ★ 持仓必须 100% 覆盖：K 线只在持仓详情里用，按 limit 截断会漏掉
    #   大部分持仓（10-05 实测：32 件里只有 6 件能查到）。
    hold_keys = load_holdings()
    hold_set = set(hold_keys) if hold_keys else set()
    hold_items, rest = [], []
    for x in items:
        (hold_items if x['hash_name'] in hold_set else rest).append(x)
    if hold_keys:
        found = {x['hash_name'] for x in hold_items}
        missing = [k for k in hold_keys if k not in found]
        print('  [%s] 持仓覆盖 %d/%d 件' % (gran, len(hold_items), len(hold_keys)),
              flush=True)
        if missing:
            print('    ⚠ 持仓里这 %d 件数据不足（%s）'
                  % (len(missing), '、'.join(missing[:4])
                     + ('…' if len(missing) > 4 else '')), flush=True)
    rest.sort(key=lambda x: (x['bars'][-1]['d'], len(x['bars'])), reverse=True)
    total = len(items)
    room = max(0, limit - len(hold_items))
    items = hold_items + rest[:room]

    # 覆盖区间：必须扫全部 bars 的最小/最大 d。
    # ⚠ 不能用 items[0]/items[-1] —— items 的顺序是「持仓优先 + 按最后一天活跃度排」，
    #   和时间顺序无关（实测会报出 2026-06-29 ~ 2026-09-28 这种假区间）。
    all_d = [b['d'] for x in items for b in x['bars']]
    span = ('%s ~ %s' % (min(all_d), max(all_d))) if all_d else '-'
    qcnt = {0: 0, 1: 0, 2: 0}
    for x in items:
        for b in x['bars']:
            qcnt[b['q']] = qcnt.get(b['q'], 0) + 1
    nb = sum(qcnt.values()) or 1
    meta = {
        'granularity': gran,
        'label': GRAN_LABEL[gran],
        'file': GRAN_FILE[gran],
        'date': time.strftime('%Y-%m-%d %H:%M'),
        'min_days': min_days,
        'min_pts_for_range': min_pts,
        'q_thresholds': {'lo': q_lo, 'hi': q_hi},
        'n': len(items),
        'total_eligible': total,
        'bars_total': len(all_d),
        'span': span,
        'q_dist': {'sparse': qcnt[0], 'fair': qcnt[1], 'dense': qcnt[2]},
        'source': 'price_history.db / prices 表',
        'channel_priority': ' > '.join(CHANNEL_PRIORITY),
        'source_note': NOTE_BY_GRAN[gran],
        'caveat': CAVEAT_BY_GRAN[gran],
    }
    print('  [%s] 密度分布 稀疏 %d(%.0f%%) / 一般 %d(%.0f%%) / 充足 %d(%.0f%%)'
          % (gran, qcnt[0], 100.0 * qcnt[0] / nb, qcnt[1], 100.0 * qcnt[1] / nb,
             qcnt[2], 100.0 * qcnt[2] / nb), flush=True)
    return items, meta


NOTE_BY_GRAN = {
    '2h': '由 price_history.db 的采样按 2 小时聚合；每个 2 小时桶内单件有 1-3 个采样点'
          '（实测64% 有 2-3 个），高低点为该桶内优先渠道（eco>buff>yy）内部采样极值',
    '1d': '由price_history.db 的采样按天聚合；一天 24 个小时全覆盖，'
          '优先渠道内单件每天 4-11 个点（实测），高低点为当天优先渠道内部采样极值',
    '1w': '由同一份采样按自然周聚合；高低点为该周内优先渠道（eco>buff>yy）内部采样极值',
}
CAVEAT_BY_GRAN = {
    '2h': '2小时K 的开收是桶内首个/末个采样点，采样非逐笔成交；'
          '桶内只有 1 个点时开=高=低=收（影线退化，q=0 时画淡）；'
          '1 小时粒度因采样集中在整点、96% 桶内只有 1 个点而无法出影线，故最小粒度定为 2 小时',
    '1d': '日K 的 high/low 是当天采样到的极值，不等于真实成交高低点；'
          '已按渠道分离，不把平台价差计入振幅；'
          '9/20 之前采集较稀疏（单件每天 3-18 点），9/20 起 57-91 点，'
          '历史越早的影线越窄，前端按每根 K 线的 q 值分级提示',
    '1w': '周K 同日K（同一份采样、同一渠道优先级），只是聚合到周；'
          '周内样本少时影线偏窄，前端按 q 值分级提示',
}


def main():
    args = parse_args()
    grans = [args.only] if args.only else ['2h', '1d', '1w']
    limits = {'2h': LIMIT_2H, '1d': LIMIT_1D, '1w': LIMIT_1W}
    if args.limit_items:
        for g in limits:
            limits[g] = args.limit_items

    conn = sqlite3.connect('file:%s?mode=ro' % DB.replace('\\', '/'), uri=True)
    conn.execute('PRAGMA cache_size=-40000')   # 2G 机器给点缓存，别用默认 2MB
    t_all = time.time()
    print('=== build_kline %s ===' % time.strftime('%Y-%m-%d %H:%M'), flush=True)

    built = []
    for gran in grans:
        # 日K/周K 无上限 → since=None（全表）；小时K 才带窗口
        since = None
        if gran == '2h':
            since = time.strftime('%Y-%m-%d',
                                  time.localtime(time.time() - args.days * 86400))
        out_path = os.path.join(args.out_dir, OUT_FILES[gran])
        print('→ %s%s' % (GRAN_LABEL[gran], ('（近 %d 天）' % args.days) if since else '（全量）'),
              flush=True)
        items, meta = build_gran(
            conn, gran, since, args.min_days, args.min_pts, args.min_hours,
            limits[gran])
        if not items:
            print('  [%s] 无合格标的，跳过' % gran, flush=True)
            continue
        payload = dict(meta)
        payload['items'] = items
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, separators=(',', ':'))
        sz = os.path.getsize(out_path)
        r0 = sum(1 for x in items for b in x['bars'] if not b['r'])
        print('  写出 %s' % os.path.basename(out_path), flush=True)
        print('  %d 件（合格 %d）· %d 根 · 覆盖 %s · %.2f MB · 影线弱 %.1f%%'
              % (len(items), meta['total_eligible'], meta['bars_total'],
                 meta['span'], sz / 1048576.0,
                 100.0 * r0 / max(1, meta['bars_total'])), flush=True)
        built.append((out_path, gran, meta))
    conn.close()
    print('全部完成，总耗时 %.1fs' % (time.time() - t_all), flush=True)

    if args.no_push:
        print('--no-push，跳过推送')
        return
    for out_path, gran, meta in built:
        push_out(out_path, gran, meta)


SIG_DIR = '.kline_pushed'


def push_out(path, gran, meta):
    """把 K 线文件推到 GitHub —— 走 update.py 同一条 Git Database API 通道。

    ⚠ 为什么必须自己推：update.py 的 push_all() 推的是它自己的 dirty_files，
      本脚本是独立 cron 跑的，不经过 update.py → kline*.json 永远不会被推上线，
      前端会一直读旧数据（而且没有任何报错，静默陈旧）。
    ⚠ 只在「内容真的变了」时才推：每天重建出来 date 字段每次都变，
      不比对就会每天提交一次几 MB 的空转 commit。
    ⚠ 推失败不抛异常：构建本身已落盘，推送失败只该告警不该让 cron 变红。
    """
    if os.environ.get('KRONOS_NO_PUSH'):
        print('  KRONOS_NO_PUSH 已设置，跳过推送', flush=True)
        return
    token = os.environ.get('GH_TOKEN') or read_gh_token()
    if not token:
        print('  ⚠ 没有 GH_TOKEN，%s 未推送（前端会读旧数据）'
              % os.path.basename(path), flush=True)
        return
    rel = os.path.relpath(path, REPO).replace('\\', '/')
    sig = file_signature(path)
    if last_pushed_sig(rel) == sig:
        print('  内容与上次推送一致，跳过 %s' % rel, flush=True)
        return
    try:
        sys.path.insert(0, REPO)
        from github_api_push import api_push_all, _ssl_ctx
        ok, failed = api_push_all(
            files=[rel],
            message=('chore(kline): 刷新%s %s（%d 件 / %d 根）'
                     % (GRAN_LABEL[gran], time.strftime('%Y-%m-%d %H:%M'),
                        meta['n'], meta['bars_total'])),
            repo=os.environ.get('KRONOS_REPO') or 'hintime/cs2-dashboard',
            token=token, ctx=_ssl_ctx(), base_dir=REPO)
        if ok:
            save_pushed_sig(rel, sig)
            print('  已推送 %s' % rel, flush=True)
        else:
            print('  ⚠ 推送失败: %s' % failed, flush=True)
    except Exception as e:
        print('  ⚠ 推送异常（不影响已生成的 %s）: %s'
              % (os.path.basename(path), e), flush=True)


def file_signature(path):
    """内容指纹：大小 + md5。只看大小会漏掉「大小相同内容不同」。"""
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return '%d:%s' % (os.path.getsize(path), h.hexdigest())


def _sig_path(rel):
    d = os.path.join(REPO, SIG_DIR)
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        return os.path.join(REPO, '.kline_pushed_%s.sig'
                            % os.path.basename(rel).replace('.json', ''))
    return os.path.join(d, os.path.basename(rel) + '.sig')


def last_pushed_sig(rel):
    try:
        with open(_sig_path(rel), encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        return ''


def save_pushed_sig(rel, sig):
    try:
        with open(_sig_path(rel), 'w', encoding='utf-8') as f:
            f.write(sig)
    except Exception:
        pass


def read_gh_token():
    """从 local_keys.env 读 GH_TOKEN（cron 环境里通常没有 → 直接读文件）。"""
    p = os.path.join(REPO, 'local_keys.env')
    try:
        with open(p, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('export '):
                    line = line[len('export '):].strip()
                if line.startswith('GH_TOKEN'):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return None


if __name__ == '__main__':
    main()
