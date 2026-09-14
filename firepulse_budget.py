#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FirePulse 额度预算器 —— 算清「给 N 条饰品做全量富化要花多少 calls」

背景
----
FirePulse 开放接口：https://open.firepulse.com.cn/open
限制：**5000 次/天**，最小间隔 1 秒（firepulse.py 内置 _MIN_INTERVAL=1.05 节流）。

真实成本模型（来自 firepulse.py，非推测）
----------------------------------------
  search_skin(name)   → /v1/wiki/skin_search   1 call  （名字 → 饰品ID）
  fetch_detail(sid)   → /v1/quote/detail       1 call  （10平台价+存世量+涨跌）
  resolve_id(name,cache) 命中缓存 → 0 call；未命中 → 1 call

因此单件成本：
  命中缓存  1 call
  未命中    2 calls          ← 首次全量富化必然是这个

固定开销（update.py 每次运行的近似值）
------------------------------------
  fetch_overview()               1
  fetch_sectors(category_type=-1) 1
  fetch_sector_overview(kline_for_top=24)  1 + 24 = 25   （已在 9/14 实测中被移除）
  fetch_overview_for_prompt()    1（若启用）
  → 保守按 3 calls/次运行

用法
----
  python firepulse_budget.py            # 用项目里的 eco_tracked.json 实测数据算
  python firepulse_budget.py --n 4807   # 指定条数
"""
import json
import os
import sys

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
DAILY_LIMIT = 5000          # FirePulse 官方日额度
MIN_INTERVAL = 1.05         # 秒/次（节流）
RUN_FIXED = 3               # 每次 update.py 运行的固定 calls 估算


def _exclude_rules(items):
    """复刻 update.py::generate_recommendations 的过滤口径，得出「真正要富化的池子」"""
    EX_PREFIX = ('StatTrak\u2122 ', 'StatTrak ', 'Souvenir ')
    EX_EXT = ('Battle-Scarred', '\u6218\u75d5\u7d2f\u7d2f', '\u7834\u635f\u4e0d\u582a')
    out = []
    for i in items:
        hn = i.get('HashName', '') or ''
        full = hn + (i.get('GoodsName', '') or '')
        if any(hn.startswith(p) for p in EX_PREFIX):
            continue
        if any(e in full for e in EX_EXT):
            continue
        try:
            if float(i.get('Price') or 0) < 20:
                continue
        except Exception:
            continue
        out.append(i)
    return out


def cost(n_items, hit_rate=0.0, fixed=RUN_FIXED):
    """返回 (calls, 占额度比例, 需要几天)

    hit_rate: ID 缓存命中率 0~1。首次全量富化 = 0。
    """
    per_item = 1.0 + (1.0 - hit_rate)      # detail 1次 + search 未命中时1次
    calls = n_items * per_item + fixed
    return calls, calls / DAILY_LIMIT, calls / DAILY_LIMIT


def report(n, label, hit_rate=0.0, fixed=RUN_FIXED):
    c, pct, days = cost(n, hit_rate, fixed)
    hours = c * MIN_INTERVAL / 3600
    print('%-26s %6d 条  %7.0f calls  %6.1f%% 额度  %5.2f h  %4.2f 天'
          % (label, n, c, pct * 100, hours, days))
    return c


def main():
    print('=' * 76)
    print('FirePulse 额度预算器   日额度 = %d calls' % DAILY_LIMIT)
    print('=' * 76)

    tp = os.path.join(DATA_DIR, 'eco_tracked.json')
    if not os.path.exists(tp):
        print('找不到 eco_tracked.json，请用 --n 指定条数')
        return
    items = json.load(open(tp, encoding='utf-8'))
    qual = _exclude_rules(items)

    print()
    print('【1】数据规模实测')
    print('  eco_tracked.json 总条数        : %d' % len(items))
    print('  过滤后（可推荐池）              : %d' % len(qual))
    print('  过滤规则：去 StatTrak / Souvenir / 战痕 / 破损，且 Price≥¥20')

    cache_path = os.path.join(DATA_DIR, 'firepulse_ids.json')
    n_cache = 0
    if os.path.exists(cache_path):
        try:
            n_cache = len(json.load(open(cache_path, encoding='utf-8')))
        except Exception:
            n_cache = 0
    print('  firepulse_ids.json 已缓存ID     : %d' % n_cache)

    print()
    print('【2】全量富化成本（首次，ID 缓存全未命中 = 2 calls/件）')
    report(len(qual), '过滤后可推荐池', 0.0)
    report(len(items), 'eco_tracked 全量', 0.0)

    print()
    print('【3】增量富化成本（ID 已缓存 = 1 call/件）')
    report(len(qual), '过滤后可推荐池', 1.0)
    report(len(items), 'eco_tracked 全量', 1.0)

    print()
    print('【4】小步快跑方案（每天跑一批，只花一部份额度）')
    for per_day in (1000, 1500, 2000, 2500):
        days = (len(qual) * 2) / per_day
        print('  每天 %5d calls（%.0f%% 额度）→ %d 条需 %.1f 天跑完'
              % (per_day, per_day / DAILY_LIMIT * 100, len(qual), days))

    print()
    print('【5】推荐池方案：只富化「榜单候选」而不是全量')
    print('  榜单 1 call = 50 条候选，再逐条富化')
    for pages in (1, 2, 5, 10):
        cand = pages * 50
        c = pages + cand          # rank 页 + 逐条富化
        print('  rank %2d 页 → %3d 候选：%3d calls（%.1f%% 额度）'
              % (pages, cand, c, c / DAILY_LIMIT * 100))

    print()
    print('【6】结论')
    full = len(qual) * 2 + RUN_FIXED
    print('  全量富化 %d 条 ≈ %d calls = %.1f%% 日额度'
          % (len(qual), full, full / DAILY_LIMIT * 100))
    print('  → %s' % ('单日额度不够，需要分批（约 %.1f 天）' % (full / DAILY_LIMIT)
                      if full > DAILY_LIMIT else '单日额度够用'))
    print('  耗时下限 %.2f 小时（受 1 call/秒 节流限制）' % (full * MIN_INTERVAL / 3600))


if __name__ == '__main__':
    main()
