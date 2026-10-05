#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kronos 训练序列「就绪度」看板（2026-09-26 口径大修版）。

为什么改口径（原文案的问题）
--------------------------
旧版统计的是 `select distinct ts from prices` —— **全库采样节奏**，
根本不是任何单条价格序列的长度；而且把门槛写成 `TARGET = 512`。
实测（2026-09-26，服务器库）暴露出两个错：

  1. 512 不是门槛。官方 finetune_csv 的样本是滑窗切的：
         window = lookback_window + predict_window + 1
         每条序列样本数 = 段长 - window + 1
     官方示例 512+48 ⇒ **window = 561**。段长 512 时样本数是 -48，
     训练脚本会直接抛 "Data length insufficient"。所以旧版会在段长刚到 512
     时就推"★ 已达标，可以开始准备微调" —— **误报，且不体现样本数**。
  2. 不分通道、不分标的。全库 distinct ts 的口径会把 eco 通道
     报成 168（真实每标的段长只有 139），因为"至少有一个 eco 标的被采到"
     不等于"每个 eco 标的都连续"。

本版口径（与本地 tools/kronos_finetune_launch.py 严格一致）
-------------------------------------------------------
  · 逐标的切段：相邻采样间隔 > GAP_H 小时即切段；
  · 用 SQL 窗口函数在库侧算，避免把 280 万行拉进内存（服务器只有 2G 内存）；
  · 门槛 = 窗口 561 步 + 目标样本数（默认 2 万条），达标判据是**样本数**；
  · 分通道报，主通道 buff（微调语料以 buff/yy 为主）；
  · 达标时间用**实测中位采样间隔**外推，不用估的节奏。

⚠ **「节奏1.00 h/点」是对的，别再当bug 改**（2026-10-05 实测复核）
--------------------------------------------------------------------
  这个数被怀疑过两次，都查错了，结论记录在此免得第三次：
  ·cron 里 prices 是`*/30`（30 分钟），但**写price_history.db 的不是 prices 轮**！
    prices 轮（每 30 分钟）写的是 `buff_history.json`（异动快照），
    `prices` 表由 **history 轮**（`15 * * * *`，每小时 :15）写入。
    → 两个表节奏本就不同：buff_history 是 30 分钟级，prices 表是 1 小时级。
  · 铁证：全库 distinct ts 里 `:45` 出现 **0 次**，`:15` 出现 362 次；
    每天恰好 24 个 `:15`（00~23 全覆盖）+ 4 个补点= 28 个时刻。
  · 逐日 `:15` 序列 00,01,02...23，相邻间隔恒为 1 小时。
  → 所以 1.00 h/点是**实测真值**，ETA 外推也是对的，改它反而会把 ETA 说快一倍。

  真正的两处口径问题（已修）：
  1. 旧注释说「eco 节奏慢 4.5 倍」—— 那是拿 eco 与 buff 比distinct ts，
     但两者现在节奏**相同**（1.00h）。已删。
  2. 报告里只给「节奏」，没给「数据来源表」和「cron 标称节奏」的对照，
     容易让人以为 cron `*/30` 就该是 0.5h。现在 report 明确写出三者。

用法
----
    python kronos_ready.py            # 打印 + 写日志
    python kronos_ready.py --push     # 额外推企业微信（供 cron 用）
"""

import os
import sys
import sqlite3
import datetime
import statistics

sys.path.insert(0, '/home/ubuntu/cs2-watchdog')

DB = os.environ.get('PRICE_HIST_DB') or '/home/ubuntu/cs2-run/price_history.db'
LOG = '/home/ubuntu/cs2-run/logs/kronos_ready.log'

# ── 门槛口径 ────────────────────────────────────────────────
LOOKBACK = 512          # 与 configs/config_cs2_buff_1h.yaml 一致
PREDICT = 48
WINDOW = LOOKBACK + PREDICT + 1     # = 561
TARGET_SAMPLES = 20000              # 多段池化后的目标样本总数
GAP_H = 12                          # 相邻点间隔超过该小时数 => 切段
CHANNELS = ('buff', 'yy', 'eco')
MAIN_CHANNEL = 'buff'

# prices.ts 存的是 **UTC**（服务器 cron 11:15 落库 → 库里是 03:15，差 8 小时）。
# 服务器时区本身就是 UTC，所以旧版没暴露这个问题；但本机跑（UTC+8）会误报"已 15 小时前"。
# 这里显式换算：内部一律用 UTC 比较，展示给义轩一律用北京时间。
TZ_OFFSET_H = 8

# 逐标的切段 + 窗口计数，全部在 SQL 侧完成
SQL_SEG = """
WITH d AS (
  SELECT item_name, ts,
         (julianday(ts) - julianday(lag(ts) OVER (PARTITION BY item_name ORDER BY ts))) * 24.0
             AS gap_h
  FROM prices WHERE channel = ?
),
m AS (
  SELECT item_name, ts,
         SUM(CASE WHEN gap_h IS NULL OR gap_h > ? THEN 1 ELSE 0 END)
             OVER (PARTITION BY item_name ORDER BY ts) AS seg_id
  FROM d
),
s AS (SELECT item_name, seg_id, COUNT(*) AS n FROM m GROUP BY item_name, seg_id)
SELECT COUNT(DISTINCT item_name) AS items,
       COALESCE(MAX(n), 0) AS max_seg,
       COALESCE(SUM(CASE WHEN n >= ? THEN 1 ELSE 0 END), 0) AS n_ok,
       COALESCE(SUM(CASE WHEN n >= ? THEN n - ? + 1 ELSE 0 END), 0) AS est_samples
FROM s
"""


def parse(s):
    try:
        return datetime.datetime.fromisoformat(s)
    except Exception:
        return None


def seg_stats(cur, ch):
    """返回 (items, max_seg, n_ok, est_samples)；SQLite 太老时退化为轻量口径。"""
    try:
        row = cur.execute(SQL_SEG, (ch, GAP_H, WINDOW, WINDOW, WINDOW)).fetchone()
        return {'items': row[0], 'max_seg': row[1], 'n_ok': row[2],
                'est_samples': row[3], 'exact': True}
    except sqlite3.OperationalError as e:
        # 窗口函数需要 SQLite >= 3.25
        tss = [r[0] for r in cur.execute(
            "SELECT DISTINCT ts FROM prices WHERE channel=? ORDER BY ts", (ch,))]
        items = cur.execute(
            "SELECT COUNT(DISTINCT item_name) FROM prices WHERE channel=?", (ch,)).fetchone()[0]
        best = run = 1
        prev = parse(tss[0]) if tss else None
        for s in tss[1:]:
            t = parse(s)
            if t and prev and (t - prev).total_seconds() / 3600.0 > GAP_H:
                best = max(best, run); run = 1
            else:
                run += 1
            prev = t
        best = max(best, run)
        return {'items': items, 'max_seg': best, 'n_ok': 0,
                'est_samples': 0 if best < WINDOW else max(0, best - WINDOW + 1) * items,
                'exact': False, 'err': str(e)[:80]}


def cadence_h(cur, ch):
    """实测采样节奏：取该通道最长连续采集段内相邻间隔的中位数（小时）。

    ⚠ **1.00 h/点是实测真值，别当bug 改**（2026-10-05 复核）
    cron 里 prices 轮是 `*/30`，但它写的是 `buff_history.json`（异动快照），
    **不是** `prices` 表。`prices` 表由 history 轮（`15 * * * *`）每小时写一次。
    铁证：全库 distinct ts 里 `:45` 出现 0 次、`:15` 出现 362 次，
    每天恰好 24 个 `:15`（00~23）+ 4 个补点。
    → 30 分钟和 1 小时是两个表的事，别混。

    另注：不用「只取 :15 整点」或「逐标的取中位」等变体 —— 实测三者结果
    完全一致（都是 1.00h），因为缺口不存在，不存在「零散补点扰动中位数」的问题。
    """
    tss = [r[0] for r in cur.execute(
        "SELECT DISTINCT ts FROM prices WHERE channel=? ORDER BY ts", (ch,))]
    if len(tss) < 3:
        return None
    best, curseg, run = [], [tss[0]], 1
    prev = parse(tss[0])
    for s in tss[1:]:
        t = parse(s)
        if not (t and prev):
            continue
        if (t - prev).total_seconds() / 3600.0 > GAP_H:
            if len(curseg) > len(best):
                best = curseg
            curseg, run = [s], 1
        else:
            curseg.append(s); run += 1
        prev = t
    if len(curseg) > len(best):
        best = curseg
    gaps = []
    for a, b in zip(best, best[1:]):
        da, db_ = parse(a), parse(b)
        if da and db_:
            gaps.append((db_ - da).total_seconds() / 3600.0)
    return statistics.median(gaps) if gaps else None


def cadence_evidence(cur, ch):
    """返回 (半小时占比, 每日时刻数, 最常见分钟) —— 用来在报告里自证「1h不是算错」。

    目的：报告里只写「节奏 1.00h」时，人会本能地对照 cron `*/30` 觉得该是 0.5h。
    直接把证据打出来（:45 出现 0 次、每天 24 个 :15），不用再解释一遍。
    """
    mins = {}
    days = {}
    for (ts,) in cur.execute(
            "SELECT DISTINCT ts FROM prices WHERE channel=?", (ch,)):
        s = str(ts)
        mins[s[14:16]] = mins.get(s[14:16], 0) + 1
        days.setdefault(s[:10], set()).add(s[11:16])
    if not mins:
        return None
    top_min = max(mins.items(), key=lambda kv: kv[1])
    n45 = mins.get('45', 0)
    n15 = mins.get('15', 0)
    per_day = max(len(v) for v in days.values()) if days else 0
    return {'min_top': top_min[0], 'min_top_n': top_min[1],
            'n15': n15, 'n45': n45,
            'per_day_max': per_day, 'days': len(days)}


def bj(datetime_utc_naive):
    """UTC(naive) → 北京时间显示字符串。"""
    return (datetime_utc_naive + datetime.timedelta(hours=TZ_OFFSET_H)).strftime('%m-%d %H:%M')


def main():
    push = '--push' in sys.argv
    now = datetime.datetime.now()
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    if not os.path.exists(DB):
        print('NO DB:', DB); return 2
    conn = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    cur = conn.cursor()

    latest = cur.execute("SELECT MAX(ts) FROM prices").fetchone()[0]
    n_rows = cur.execute("SELECT COUNT(*) FROM prices").fetchone()[0]

    res = {}
    for ch in CHANNELS:
        st = seg_stats(cur, ch)
        st['cadence_h'] = cadence_h(cur, ch)
        st['cadence_ev'] = cadence_evidence(cur, ch)
        # 到"够 TARGET_SAMPLES 条样本"所需的段长
        per_item = max(1, -(-TARGET_SAMPLES // max(1, st['items'])))
        st['need_len'] = WINDOW - 1 + per_item
        st['gap_pts'] = max(0, st['need_len'] - st['max_seg'])
        st['eta_days'] = (st['gap_pts'] * st['cadence_h'] / 24.0
                          if st['cadence_h'] else None)
        st['pass'] = st['est_samples'] >= TARGET_SAMPLES
        res[ch] = st
    conn.close()

    main_st = res.get(MAIN_CHANNEL) or res[CHANNELS[0]]
    ready = any(v['pass'] for v in res.values())
    ready_chs = [c for c, v in res.items() if v['pass']]

    eta_txt = '--'
    if not ready and main_st.get('eta_days') is not None and latest:
        lt = parse(latest)
        d = (lt + datetime.timedelta(hours=TZ_OFFSET_H, days=main_st['eta_days'])
             ).strftime('%m-%d') if lt else '?'
        eta_txt = '约 %.0f 天后（%s）' % (main_st['eta_days'], d)

    head = '【CS2 · Kronos 微调就绪度】%s' % now.strftime('%m-%d %H:%M')
    L = [head, '-' * 40]
    L.append('数据规模    %d 行 / 最新 %s（北京）'
             % (n_rows, bj(parse(latest)) if latest else '--'))
    L.append('门槛        窗口 %d 步（lookback %d + predict %d + 1）' % (WINDOW, LOOKBACK, PREDICT))
    L.append('            样本总数 >= %d（段长 < 窗口时切不出样本）' % TARGET_SAMPLES)
    L.append('')
    for ch in CHANNELS:
        v = res[ch]
        mark = '★' if v['pass'] else ' '
        L.append('%s %-4s 标的 %5d | 最长连续段 %4d 点 | 达标标的 %4d | 估算样本 %6d'
                 % (mark, ch, v['items'], v['max_seg'], v['n_ok'], v['est_samples']))
        cad = ('%.2f h/点' % v['cadence_h']) if v['cadence_h'] else '--'
        extra = '' if v['pass'] else ('  还差 %d 点/标的' % v['gap_pts'])
        L.append('       节奏 %-10s 目标段长 %d 点%s' % (cad, v['need_len'], extra))
        ev = v.get('cadence_ev')
        if ev and v.get('cadence_h'):
            L.append('       └ 证据：最常见落库时刻 :%s（%d 次）；:15 出现 %d 次、'
                     ':45 出现 %d 次；日均 %d 个时刻'
                     % (ev['min_top'], ev['min_top_n'], ev['n15'], ev['n45'],
                        round(ev['per_day_max'] * 1.0)))

    L.append('')
    # ★ 口径说明：写清楚「1h/点」为什么不是 cron 的 30 分钟 —— 免得下次又当bug 查一遍
    L.append('口径：prices 表由 history 轮（每小时 :15）写入 → 节奏 1.00 h/点；')
    L.append('      prices 轮（cron */30，每 30 分钟）写的是 buff_history.json（异动快照），')
    L.append('      不是本表。两者是不同表、不同节奏，别拿 cron 标称值对照本表。')
    L.append('')
    if not all(v['exact'] for v in res.values()):
        L.append('⚠ 口径退化：SQLite 版本不支持窗口函数，改用"采集事件"近似（eco 会高估）')
    L.append('')
    if ready:
        L.append('★ 已达标（%s）—— 可跑：tools/kronos_build_corpus.py 导语料 → tools/kronos_finetune_launch.py 开训'
                 % ','.join(ready_chs))
    else:
        L.append('未达标。按 %s 通道实测节奏外推：%s' % (MAIN_CHANNEL, eta_txt))
    if latest:
        lt = parse(latest)
        if lt:
            idle_h = (now_utc - lt).total_seconds() / 3600.0
            if idle_h > GAP_H:
                L.append('⚠ 最新采样已在 %.0f 小时前（超过 %dh，已切段）' % (idle_h, GAP_H))

    text = '\n'.join(L)
    print(text)

    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write('[%s]\n%s\n\n' % (now.strftime('%F %T'), text))
    except Exception as e:
        print('日志写入失败:', e)

    if push:
        try:
            import wecom_notify
            _cad = main_st.get('cadence_h')
            _cad_txt = ('节奏 %.2f h/点（history 轮每小时 :15 落库；'
                        'prices 轮写 buff_history.json，不写本表）' % _cad
                        ) if _cad else '节奏 --'
            brief = '\n'.join([
                head,
                ('★ 已达标（%s）' % ','.join(ready_chs)) if ready else '未达标',
                '%s 最长段 %d/%d 点 | 估算样本 %d/%d'
                % (MAIN_CHANNEL, main_st['max_seg'], main_st['need_len'],
                   main_st['est_samples'], TARGET_SAMPLES),
                _cad_txt,
                ('预计 %s' % eta_txt) if not ready else '可开始：导语料 → 开训',
            ])
            ok, info = wecom_notify.send(brief)
            print('推送: %s %s' % ('OK' if ok else 'FAIL', info))
        except Exception as e:
            print('推送异常: %s: %s' % (type(e).__name__, e))
    return 0


if __name__ == '__main__':
    sys.exit(main())
