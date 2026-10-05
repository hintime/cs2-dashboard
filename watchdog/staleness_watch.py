#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CS2 生成物停更监控（staleness watchdog）。

为什么需要
----------
2026-10-04 体检发现：`update.py` 第 4706 行在 `main()` 内部有一句多余的
`import json`，把 `json` 变成局部变量 → 4573 行 `json.load(...)` 抛
UnboundLocalError → 被 `except` 吞掉只打 stderr。结果 `name_map.json`
**静默停更 13 天**（约 500 轮 cron 全失败，日志里只有一行看不懂的
UnboundLocalError）。

这类「不抛异常、只写 stderr」的失败，人工扫 except 抓不到 —— 本监控用
「生成物 mtime 是否符合它的采集周期」来判定，绕开代码层，直接盯结果。

设计要点
--------
1. **阈值按 group 配，不逐文件写死**。每组给一个 max_age_min，由 cron 的
   真实周期 × SAFETY 推出。新增生成物时归到最接近的组即可。
2. **mtime > now 的文件要能容忍**：服务器 clock 抖动 / 未来时间戳的
   文件（如从别处 rsync 来的）会让 (now - mtime) 为负，算出「刚刚更新」
   反而掩盖问题。这里钳到 0。
3. **缺文件单独报**：文件不存在是比「停更」更严重的问题（可能被手动删了
   或生成路径变了），必须区分开。
4. **静态文件显式豁免**：`cost-overrides.json` 这类手工维护的要有
   opt-out，否则天天误报。
5. **告警节流**：问题清单变化立刻推；持续未变按 REMIND_HOURS 重推；
   恢复推一条。这套逻辑与 watchdog/check.py 保持一致，避免两套节奏打架。

用法
----
    python3 staleness_watch.py            # 巡检 + 按需推送
    python3 staleness_watch.py --dry      # 只打印不推送
    python3 staleness_watch.py --init     # 生成/刷新 SPEC（按当前 mtime 建基线）
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
import time

REPO = '/home/ubuntu/cs2-run'
D = os.path.join(REPO, 'watchdog')
RESULT = os.path.join(D, 'staleness_result.json')
LOG = os.path.join(D, 'staleness.log')
NOTIFY = os.path.join(D, 'wecom_notify.py')

# ── 分组阈值（分钟）──
# cron 实测周期：prices 30min / index 2h / all 6h / history 1h。
# 倍数不统一是刻意的：all 轮本身常跑 10-20 分钟、history 轮要抓 2791 件
# ECO 现价（约 5-8 分钟），周期短的组留 3× 余量避免偶发超时误报。
GROUPS = {
    'prices': 90,     # 30min × 3
    'index':  330,    # 2h × 2.75
    'all':    900,    # 6h × 2.5 → 15 小时
    'daily':  2880,   # 1/天
    'static': 0,      # 0 = 永不告警
}

# 组 → 对应 cron 日志（出问题时好去翻是哪轮报的错）
GROUP_LOG = {
    'prices': 'cron_prices',
    'index':  'cron_index',
    'all':    'cron_all',
    'daily':  'cron_all',
}

# ── 文件 → 组 ──
# 依据（2026-10-04 逐个 grep 生产者确认，不靠猜）：
#   · update.py 里 dirty_files.add() 的 mode 分支
#   · cron 实测周期：prices 30min / index 2h / all 6h / history 1h
#   · 独立脚本（tracking_ai.py / event_study.py / steam_market.py）的调用点
# 调阈值前请用 `grep -rn '<文件名>' --include=*.py .` 确认生产者与轮次。
SPEC = {
    # 30min prices 轮：价格/盘口快照
    'buff_recent.json':        'prices',
    'fluct_recent.json':       'prices',
    'market.json':             'prices',
    'holdings.json':           'prices',
    'price_summary.json':      'prices',
    'track_view.json':         'prices',
    'firepulse_ids.json':      'prices',
    'buff_history.json':       'prices',

    # all 轮（6h）：汇总/评分/状态
    'data_status.json':        'all',
    'correlation_data.json':   'all',   # generate_correlation.main()
    'tracking_analysis.json':  'all',
    'tracking_lessons.json':   'all',
    'sectors.json':            'all',
    'market_overview.json':    'all',
    'market_overview_history.json': 'all',
    'market_sectors.json':     'all',
    'daily_report.json':       'all',
    'market_scan.json':        'all',
    'ai_analysis.json':        'all',
    'ai_daily_report.json':    'all',
    'ai_anomaly.json':         'all',
    'ai_market_insight.json':  'all',
    'ai_news_impact.json':     'all',
    'ai_stock_picks.json':     'all',
    'ai_recommendations.json': 'all',
    'ai_meta.json':            'all',
    'changelog.json':          'all',
    'eco_tracked.json':        'all',
    'eco_catalog.json':        'all',   # eco_catalog.build()，all 轮后台线程
    # ★ name_map 就是 10-04 抓到停更 13 天的那个（update.py:4579）
    'name_map.json':           'all',
    # ai_forecast 挂在 all 轮（update.py:939 调 kronos_forecast_srv.py），不是 history
    'ai_forecast.json':        'all',
    # event_study 与 ai_forecast 同一段（update.py:4496，跟在 run_kronos_forecast 后）
    'event_study.json':        'all',
    # update.py:4532 在 `if mode in ('all','market')` 内；cron 没有 market 轮 → 实际只由 all 产出
    'market_history.json':     'all',

    # history 轮（1h）：盘口落库
    # 注：history 轮只写 price_history.db（SQLite），不产 json —— 别把 json 挂到这组

    # 日更
    'news.json':               'daily',
    'news_history.json':       'daily',
    'csqaq_boards.json':       'daily',     # 盘口快照，一天一条
    'rec_tracks.json':         'daily',     # tracking_ai.py：每天一个快照键

    # 静态 / 手工维护：豁免
    'cost-overrides.json':     'static',
    'vercel.json':             'static',
    'rec_tag_map.json':        'static',   # 304 名历史台账，无 py 写它
    'history.json':            'static',   # 5 月死文件
}

REMIND_HOURS = 6


def log(msg):
    line = '%s %s' % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), msg)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass
    print(line, flush=True)


def stat_mtime(fn):
    """返回文件的 mtime；不存在返回 None。"""
    p = os.path.join(REPO, fn)
    try:
        return os.stat(p).st_mtime
    except OSError:
        return None


def check():
    """返回 (problems, facts)。"""
    problems, facts = [], {}
    now = time.time()
    rows = []
    for fn in sorted(SPEC):
        grp = SPEC[fn]
        mx = GROUPS.get(grp, 0)
        mt = stat_mtime(fn)
        if mx == 0:                     # static：豁免但仍记录，便于排查
            rows.append((fn, grp, -1, -1))
            continue
        if mt is None:
            problems.append('%s 缺失（%s 轮本应产出）' % (fn, grp))
            rows.append((fn, grp, None, None))
            continue
        # 钳到 0：mtime 在未来（clock 抖动 / rsync 来的文件）不掩盖问题
        age_min = max(0.0, (now - mt) / 60.0)
        rows.append((fn, grp, age_min, mx))
        if age_min > mx:
            problems.append('%s 已 %.1f 小时未更新（阈值 %.1f 小时 · %s 轮）'
                            % (fn, age_min / 60.0, mx / 60.0, grp))
    facts['checked'] = len(SPEC)
    facts['missing'] = sum(1 for r in rows if r[2] is None)
    stale = [r for r in rows if r[2] is not None and r[3] and r[2] > r[3]]
    facts['stale'] = len(stale)
    facts['rows'] = [{'file': r[0], 'group': r[1],
                      'age_min': (None if r[2] is None else round(r[2], 1)),
                      'max_min': (None if r[3] is None or r[3] < 0 else r[3])}
                     for r in rows]
    return problems, facts


def load_old():
    try:
        with open(RESULT, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def decide(old, problems, now):
    old_problems = old.get('problems') or []
    last_push = old.get('last_push') or 0
    if problems and problems != old_problems:
        return True, '新问题/问题变化'
    if problems and (now - last_push) > REMIND_HOURS * 3600:
        return True, '问题持续 %.0f 小时未解决，重提醒' % REMIND_HOURS
    if not problems and old_problems:
        return True, '已恢复'
    return False, ''


def build_msg(problems, facts, old_problems, reason):
    t = datetime.datetime.now().strftime('%m-%d %H:%M')
    if not problems:
        return ("【CS2 看板】生成物全部正常\n"
                "时间: %s\n"
                "之前的问题: %s\n"
                "现状: 监控 %d 个生成物，缺失 0、停更 0"
                % (t, '；'.join(old_problems) if old_problems else '(无)',
                   facts.get('checked', 0)))
    lines = ['【CS2 看板】生成物停更告警', '时间: ' + t, '问题:']
    for p in problems[:12]:
        lines.append(' · ' + p)
    if len(problems) > 12:
        lines.append(' · …另有 %d 项' % (len(problems) - 12))
    lines.append('监控 %d 个生成物：缺失 %s、停更 %s'
                 % (facts.get('checked', 0), facts.get('missing', 0),
                    facts.get('stale', 0)))
    lines.append('(触发: %s)' % reason)
    lines.append('定位: 去 logs/cron_%s.log 搜 failed/skipped/Error；'
                 '此类问题都是 update.py 里被 except 吞掉的异常'
                 % GROUP_LOG.get(_guess_mode(problems), 'all'))
    return '\n'.join(lines)


def _guess_mode(problems):
    """从问题条目里猜是哪个 mode 的轮，出错时好去对应日志里查。"""
    txt = ' '.join(problems)
    for fn, grp in SPEC.items():
        if fn in txt:
            return grp
    return 'all'


def push(msg):
    try:
        subprocess.run([sys.executable, NOTIFY, msg], cwd=REPO,
                       timeout=30, capture_output=True)
    except Exception as e:
        log('推送失败(非致命): %s' % e)


def print_table(facts):
    rows = facts.get('rows') or []
    print()
    print('%-30s %-8s %10s %10s' % ('file', 'group', 'age(min)', 'max(min)'))
    print('-' * 64)
    for r in sorted(rows, key=lambda x: (x['group'], x['file'])):
        if r['age_min'] is None:
            print('%-30s %-8s %10s %10s  <== 缺失'
                  % (r['file'], r['group'], '-', r['max_min'] or '-'))
        elif r['max_min'] is None or r['max_min'] < 0:
            print('%-30s %-8s %10.1f %10s  (豁免)'
                  % (r['file'], r['group'], r['age_min'], 'static'))
        else:
            flag = '  <== 超阈' if r['age_min'] > r['max_min'] else ''
            print('%-30s %-8s %10.1f %10.1f%s'
                  % (r['file'], r['group'], r['age_min'], r['max_min'], flag))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true', help='只巡检不推送')
    ap.add_argument('--init', action='store_true', help='按当前 mtime 建基线（不推）')
    a = ap.parse_args()

    problems, facts = check()
    print_table(facts)
    log('巡检 %d 个生成物 → 缺失 %d、停更 %d'
        % (facts.get('checked', 0), facts.get('missing', 0), facts.get('stale', 0)))
    for p in problems:
        log('  PROBLEM: ' + p)

    if a.init:
        json.dump({'problems': problems, 'facts': facts, 'last_push': 0},
                  open(RESULT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        log('--init 完成，基线已写入 %s' % RESULT)
        return

    old = load_old()
    now = time.time()
    do_push, reason = decide(old, problems, now)
    if a.dry:
        log('--dry：不推送（would_push=%s, reason=%s）' % (do_push, reason))
        return
    if do_push:
        push(build_msg(problems, facts, old.get('problems') or [], reason))
        log('已推送: %s' % reason)
    else:
        log('无需推送（问题清单未变化）')
    json.dump({'problems': problems, 'facts': facts,
               'last_push': (now if do_push else old.get('last_push') or 0),
               'ts': now},
              open(RESULT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
