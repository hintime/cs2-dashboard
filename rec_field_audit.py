# -*- coding: utf-8 -*-
"""推荐字段覆盖率体检（找「UI 在显示、数据恒空」的假功能）。

做法：遍历 market.json 的推荐条目，统计每个字段的"非空/非0"覆盖率：
  · coverage == 0            → 死字段（UI 可能永远空白）
  · 0 < coverage < 40%       → 覆盖偏低
并与上次基线（outputs/rec_field_baseline.json）对比，突出 **新增死字段** 与 **恢复的字段**。
新增死字段（且不在允许清单）→ 退出码 1，便于自动化告警。

用法：python rec_field_audit.py [--update-baseline]
"""
import json, os, sys, datetime as dt

REPO = os.environ.get('CS2_REPO') or r'C:\Users\Lenovo\cs2-runner-local'
OUT_DIR = os.path.join(REPO, 'outputs')
AUDIT = os.path.join(OUT_DIR, 'rec_field_audit.json')
BASE = os.path.join(OUT_DIR, 'rec_field_baseline.json')

# 允许存在的死字段（有正当理由的空值字段写这里；目前为空 = 任何死字段都告警）
ALLOW_DEAD = set()


def coverage(items, key):
    n = 0
    for it in items:
        v = it.get(key)
        if v is None or v == '' or v == [] or v == {}:
            continue
        if isinstance(v, (int, float)) and v == 0:
            continue
        n += 1
    return n


def main():
    update_baseline = '--update-baseline' in sys.argv
    mkt = json.load(open(os.path.join(REPO, 'market.json'), encoding='utf-8'))
    items = (mkt.get('recommendations') or {}).get('all') or []
    if not items:
        print('[AUDIT] market.json 无推荐条目，跳过'); return 0

    keys = set()
    for it in items:
        keys |= set(it.keys())
    total = len(items)
    cov = {k: coverage(items, k) for k in sorted(keys)}
    dead = [k for k, c in cov.items() if c == 0]
    low = [(k, c) for k, c in cov.items() if 0 < c < total * 0.4]

    prev = {}
    if os.path.exists(BASE):
        try:
            prev = json.load(open(BASE, encoding='utf-8')).get('coverage', {})
        except Exception:
            prev = {}

    new_dead = [k for k in dead if k not in prev or prev.get(k, 0) > 0]
    recovered = [k for k, c in cov.items() if c > 0 and prev.get(k, 0) == 0]
    vanished = [k for k in prev if k not in cov]

    print('=== 推荐字段覆盖率体检（%d 条）===' % total)
    print('死字段(0 覆盖): %s' % (dead if dead else '无 ✓'))
    print('覆盖偏低(<40%%): %s' % ([('%s %d/%d' % (k, c, total)) for k, c in low] or '无'))
    if new_dead:
        print('★ 新增死字段: %s' % new_dead)
    if recovered:
        print('↗ 恢复/新产出的字段: %s' % recovered)
    if vanished:
        print('↘ 消失的字段(基线有、现在没有): %s' % vanished)

    report = {'generated': dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
              'total': total, 'coverage': cov, 'dead': dead,
              'low': [{'key': k, 'n': c} for k, c in low],
              'new_dead': new_dead, 'recovered': recovered, 'vanished': vanished,
              'allow_dead': sorted(ALLOW_DEAD)}
    os.makedirs(OUT_DIR, exist_ok=True)
    json.dump(report, open(AUDIT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    if update_baseline:
        json.dump({'generated': report['generated'], 'coverage': cov},
                  open(BASE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print('基线已更新 →', BASE)
    print('报告 →', AUDIT)

    # 未修复的新增死字段 → 非 0 退出（供自动化告警）
    alarm = [k for k in new_dead if k not in ALLOW_DEAD]
    return 1 if alarm else 0


if __name__ == '__main__':
    sys.exit(main())
