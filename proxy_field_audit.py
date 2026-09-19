# -*- coding: utf-8 -*-
"""代理/估算字段体检：定期抽样对比真实值 + 跨源一致性检查。

为什么需要：本次发现「存世量」长期用 eco_selling（在售件数）**代理**，
与真实存世量差 33~384 倍，而它同时被用于展示与排序 —— 没人核对过量级。

三类检查（注册表可扩展）：
  · ratio      代理值 vs 真实值 的偏离倍数（代理若被当"真值"用且偏差过大 → 告警）
  · identical  两个字段应当不同却恒等 → 命名冗余/重复维护
  · cross      同一指标两个独立来源应当吻合 → 偏离过大说明有一方错了

用法：python proxy_field_audit.py [--update-baseline]
退出码 1 = 有告警（供自动化点名）。
"""
import json, os, statistics, sys, datetime as dt

REPO = os.environ.get('CS2_REPO') or r'C:\Users\Lenovo\cs2-runner-local'
OUT_DIR = os.path.join(REPO, 'outputs')
AUDIT = os.path.join(OUT_DIR, 'proxy_field_audit.json')

# ── 注册表：新增代理/估算字段时在这里登记 ──
RATIO_CHECKS = [
    {'id': 'supply_proxy', 'label': '存世量代理',
     'proxy': 'eco_selling', 'real': 'n_supply_real',
     'note': '用「在售件数」代替真实存世量', 'primary': False,
     'alarm_ratio': 10.0},
    {'id': 'supply_proxy_old', 'label': '存世量代理(旧字段名 n_supply)',
     'proxy': 'n_supply', 'real': 'n_supply_real',
     'note': 'n_supply 实为在售件数（与 eco_selling 恒等）', 'primary': False,
     'alarm_ratio': 10.0},
]
IDENTICAL_CHECKS = [
    # ── 以下三组在 2026-09-19 已确认为「**有意别名**」，非 bug ──
    #   处理方式：源头改为「一处取值 + 显式别名」（update.py 推荐条目构建处），
    #   恒等是契约的一部分。此处保留检查，用于**发现未来有人破坏该契约**
    #   （例如给其中一个字段单独赋值 → 恒等率掉下来 → 立刻告警）。
    {'id': 'ref_steam', 'a': 'n_ref', 'b': 'n_steam',
     'note': '有意别名：normalize 的 ref_price 实际只走 steam_sell 一路（eco_platform_price 全池无值）',
     'expect_identical': True},
    {'id': 'selling_supply', 'a': 'eco_selling', 'b': 'n_supply',
     'note': '有意别名：同源 SellingTotal；n_supply 是「存世量」代理、非真值',
     'expect_identical': True},
    {'id': 'price_eco', 'a': 'price', 'b': 'eco_price',
     'note': '有意别名：同源 ECO 低位档价 item[Price]',
     'expect_identical': True},
]
CROSS_CHECKS = [
    # buff_sell 会被 SteamDT 覆盖成它的值；_csqaq_buff 是 CSQAQ 原值 →
    # 两者**相异**时才是真正的「两个独立来源」，才有比对价值。
    {'id': 'buff_two_sources', 'label': 'BUFF 在售价（SteamDT 现值 vs CSQAQ 原值）',
     'a': 'buff_sell', 'b': '_csqaq_buff', 'max_dev_pct': 5.0,
     'note': '两个独立来源应当基本吻合；同值样本不计入'},
]


def _num(v):
    f = float(v) if isinstance(v, (int, float)) else None
    return f if (f is not None and f > 0) else None


def main():
    base = os.path.exists(AUDIT) and json.load(open(AUDIT, encoding='utf-8')) or {}
    prev = base.get('summary', {})
    mkt = json.load(open(os.path.join(REPO, 'market.json'), encoding='utf-8'))
    items = (mkt.get('recommendations') or {}).get('all') or []
    if not items:
        print('[PROXY] market.json 无推荐条目，跳过'); return 0

    alarms, notes, summary = [], [], {}

    print('=== 代理/估算字段体检（%d 条推荐）===' % len(items))
    print('[比例检查] 代理 vs 真实')
    for c in RATIO_CHECKS:
        pairs = []
        for it in items:
            p, r = _num(it.get(c['proxy'])), _num(it.get(c['real']))
            if p and r:
                pairs.append(max(p, r) / min(p, r))     # 偏离倍数（对称）
        if not pairs:
            print('  %-28s 无配对样本' % c['label']); continue
        med, mx = statistics.median(pairs), max(pairs)
        n = len(pairs)
        summary[c['id']] = {'n': n, 'median_ratio': round(med, 1), 'max_ratio': round(mx, 1)}
        flag = '⚠ 告警' if (c.get('primary') and med > c['alarm_ratio']) else 'ℹ 仅记录'
        if c.get('primary') and med > c['alarm_ratio']:
            alarms.append('%s：中位偏离 %.0f 倍（阈值 %.0f）且被当作真值使用' % (c['label'], med, c['alarm_ratio']))
        print('  %-28s n=%-3d 中位偏离 %6.1f 倍  最大 %6.1f 倍  %s（%s）'
              % (c['label'], n, med, mx, flag, c['note']))
        notes.append('%s：中位偏离 %.0f 倍%s' % (c['label'], med,
                                               '（当前仅作兜底，已在后端标注 *代理）' if not c.get('primary') else ''))

    print('[恒等检查] 本应不同却恒等 / 或本应恒等的别名被破坏')
    for c in IDENTICAL_CHECKS:
        pairs = [(_num(it.get(c['a'])), _num(it.get(c['b']))) for it in items]
        pairs = [(a, b) for a, b in pairs if a and b]
        if not pairs:
            print('  %-28s 无配对样本' % c['id']); continue
        same = sum(1 for a, b in pairs if abs(a - b) < 1e-9)
        pct = same / len(pairs) * 100
        summary[c['id']] = {'n': len(pairs), 'identical_pct': round(pct, 1)}
        # 「预期恒等」的别名：恒等率跌破 99% 说明有人给其中一个字段单独赋值 → 契约被破坏
        if c.get('expect_identical'):
            broken = pct < 99.0
            if broken:
                alarms.append('%s：别名契约被破坏（恒等率仅 %.0f%%，应 ≈100%%）' % (c['id'], pct))
            print('  %-28s %s ≡ %s  恒等 %.0f%%  %s（%s）'
                  % (c['id'], c['a'], c['b'], pct, '⚠ 契约破坏' if broken else '✓ 契约成立', c['note']))
        else:
            print('  %-28s %s vs %s  恒等 %.0f%%（%s）' % (c['id'], c['a'], c['b'], pct, c['note']))

    print('[跨源检查] 同一指标两个来源')
    for c in CROSS_CHECKS:
        devs = []
        same = 0
        for it in items:
            a, b = _num(it.get(c['a'])), _num(it.get(c['b']))
            if a and b:
                if abs(a - b) < 1e-9:
                    same += 1          # 同值 = 同一来源，无比对价值
                else:
                    devs.append(abs(a - b) / ((a + b) / 2) * 100)
        if not devs:
            print('  %-28s 无有效样本（%d 对同值：SteamDT 尚未覆盖这些标的）' % (c['label'], same)); continue
        med, mx = statistics.median(devs), max(devs)
        summary[c['id']] = {'n': len(devs), 'median_dev_pct': round(med, 2), 'max_dev_pct': round(mx, 2)}
        bad = med > c['max_dev_pct']
        if bad:
            alarms.append('%s：中位偏差 %.1f%% 超阈值 %.1f%%（可能有一方数据错了）'
                          % (c['label'], med, c['max_dev_pct']))
        print('  %-28s n=%-3d 中位偏差 %5.2f%%  最大 %6.2f%%  %s'
              % (c['label'], len(devs), med, mx, '⚠ 告警' if bad else '✓ 正常'))

    print()
    if alarms:
        print('★ 告警 %d 条：' % len(alarms))
        for a in alarms:
            print('   -', a)
    else:
        print('★ 无告警 ✓')
    for n_ in notes:
        print('   note:', n_)

    json.dump({'generated': dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
               'n_items': len(items), 'summary': summary,
               'alarms': alarms, 'notes': notes},
              open(AUDIT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('报告 →', AUDIT)
    return 1 if alarms else 0


if __name__ == '__main__':
    sys.exit(main())
