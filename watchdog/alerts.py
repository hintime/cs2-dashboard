#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""异动主动推送（2026-09-21 义轩要求：有异动要主动发信息给我）

数据源
  · 价格异动 → market_scan.json 的 movers（已由 generate_scan 算好）
  · 盘口异动 → price_db.get_board_movers()（在售/求购的相邻采样变化）

推送策略（刻意克制，避免刷屏打扰）
  · 只在超过阈值时推；每次合并成**一条**消息，不是一条一推
  · 同一标的同类异动 COOLDOWN_H 小时内只推一次（alerts_sent.json 记账）
  · 每类最多 MAX_PER_KIND 条
  · 首次运行只建立基线不推送（否则一上线就糊用户一脸）

阈值可用环境变量覆盖：ALERT_PRICE_PCT / ALERT_SUPPLY_PCT / ALERT_SUPPLY_MIN
                       ALERT_DEMAND_PCT / ALERT_DEMAND_MIN / ALERT_COOLDOWN_H
"""
import os
import sys
import json
import time

D = '/home/ubuntu/cs2-run/watchdog'
RUN = '/home/ubuntu/cs2-run'
SENT = os.path.join(D, 'alerts_sent.json')

PRICE_PCT = float(os.environ.get('ALERT_PRICE_PCT') or 12)
SUPPLY_PCT = float(os.environ.get('ALERT_SUPPLY_PCT') or 30)
SUPPLY_MIN = int(os.environ.get('ALERT_SUPPLY_MIN') or 20)
DEMAND_PCT = float(os.environ.get('ALERT_DEMAND_PCT') or 50)
DEMAND_MIN = int(os.environ.get('ALERT_DEMAND_MIN') or 10)
COOLDOWN_H = float(os.environ.get('ALERT_COOLDOWN_H') or 6)
MAX_PER_KIND = 3


def _load(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _cn_map():
    """HashName → 中文名（boards 表存英文名，推送要给玩家看的中文）"""
    m = {}
    items = _load(os.path.join(RUN, 'eco_tracked.json'), []) or []
    for it in items:
        if not isinstance(it, dict):
            continue
        h = it.get('HashName') or ''
        g = it.get('GoodsName') or ''
        if h and g:
            m[h] = g
    return m


def collect():
    """收集本期异动 → [(key, kind, line)]，kind ∈ price/supply/demand"""
    out = []
    cn = _cn_map()

    # ── 1. 价格异动（market_scan.json，已带中文名）──
    sc = _load(os.path.join(RUN, 'market_scan.json'), {}) or {}
    mv = sc.get('movers') or {}
    for key, sign in (('gainers', '▲'), ('losers', '▼')):
        for x in (mv.get(key) or [])[:MAX_PER_KIND]:
            try:
                c = float(x.get('r7') or 0)
                p = float(x.get('p') or 0)
            except (TypeError, ValueError):
                continue
            if abs(c) < PRICE_PCT:
                continue
            nm = str(x.get('n') or '')
            out.append(('price|%s' % nm, 'price',
                        '%s %s  %+.1f%%  ¥%g' % (sign, nm, c, p)))

    # ── 2. 盘口异动（在售 / 求购）──
    try:
        sys.path.insert(0, RUN)
        import price_db as P
        bm = P.get_board_movers(steps=1, limit=8)
        for x in ((bm.get('sell') or {}).get('add') or []):
            if x.get('old', 0) >= SUPPLY_MIN and (x.get('pct') or 0) >= SUPPLY_PCT:
                nm = cn.get(x.get('name'), x.get('name'))
                out.append(('supply|%s' % x.get('name'), 'supply',
                            '▲ %s  在售 %d→%d 件 (+%.0f%%)'
                            % (nm, x.get('old', 0), x.get('new', 0), x.get('pct') or 0)))
        for x in ((bm.get('sell') or {}).get('drop') or []):
            if x.get('old', 0) >= SUPPLY_MIN and abs(x.get('pct') or 0) >= SUPPLY_PCT:
                nm = cn.get(x.get('name'), x.get('name'))
                out.append(('supply|%s' % x.get('name'), 'supply',
                            '▼ %s  在售 %d→%d 件 (%.0f%%)'
                            % (nm, x.get('old', 0), x.get('new', 0), x.get('pct') or 0)))
        for x in ((bm.get('buy') or {}).get('add') or []):
            if x.get('old', 0) >= DEMAND_MIN and (x.get('pct') or 0) >= DEMAND_PCT:
                nm = cn.get(x.get('name'), x.get('name'))
                out.append(('demand|%s' % x.get('name'), 'demand',
                            '▲ %s  求购 %d→%d 个 (+%.0f%%)'
                            % (nm, x.get('old', 0), x.get('new', 0), x.get('pct') or 0)))
    except Exception as e:
        print('[ALERT] 盘口读取失败（跳过）: %s: %s' % (type(e).__name__, e), file=sys.stderr)

    return out


def build_msg(fresh, now):
    """合并成一条消息：价格 / 在售 / 求购 三节"""
    t = time.strftime('%m-%d %H:%M', time.localtime(now))
    L = ['【CS2 异动提醒 · %s】' % t]
    titles = [('price', '价格'),
              ('supply', '在售变化（▼ 减少=有人扫货 / ▲ 增加=卖压）'),
              ('demand', '求购变化')]
    for kind, title in titles:
        rows = [x[2] for x in fresh if x[1] == kind][:MAX_PER_KIND]
        if not rows:
            continue
        L.append('')
        L.append('■ %s' % title)
        L.extend('  ' + r for r in rows)
    return '\n'.join(L)


def run(push=True, force=False):
    """返回推送条数；push=False 时只算不发（试跑用）"""
    now = time.time()
    first_run = not os.path.exists(SENT)
    items = collect()
    sent = _load(SENT, {}) or {}
    fresh = [x for x in items
             if force or (now - float(sent.get(x[0]) or 0)) > COOLDOWN_H * 3600]

    if first_run and not force:
        # 首次上线：只建基线，不推送（否则一装好就糊一堆历史异动）
        for k, _kind, _line in items:
            sent[k] = now
        try:
            with open(SENT, 'w', encoding='utf-8') as f:
                json.dump(sent, f, ensure_ascii=False, indent=1)
        except OSError:
            pass
        print('[ALERT] 首次运行：已建立基线 %d 条，本次不推送' % len(items))
        return 0

    if not fresh:
        print('[ALERT] 本期无异动（候选 %d 条，均在冷却期内）' % len(items))
        return 0

    msg = build_msg(fresh, now)
    if not push:
        print('[ALERT] 试跑模式，不发送。消息如下：')
        print(msg)
        return len(fresh)

    try:
        import wecom_notify
        ok, info = wecom_notify.send(msg, touser='@all')
        print('[ALERT] 推送 %s（%d 条）: %s' % ('成功' if ok else '失败', len(fresh), info))
        if not ok:
            return 0
    except Exception as e:
        print('[ALERT] 推送异常: %s: %s' % (type(e).__name__, e), file=sys.stderr)
        return 0

    for k, _kind, _line in fresh:
        sent[k] = now
    try:
        with open(SENT, 'w', encoding='utf-8') as f:
            json.dump(sent, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return len(fresh)


if __name__ == '__main__':
    force = '--force' in sys.argv
    dry = '--dry' in sys.argv
    n = run(push=not dry, force=force)
    sys.exit(0)
