# -*- coding: utf-8 -*-
"""统一数据层：ECO / SteamDT / CSQAQ / FirePulse 四源归一化。

设计目标
--------
上游（评分、推荐、前端）**只读本层输出的统一字段**，不再自己到处取价。
每个统一字段都带 `_src` 标记来源、`_conf` 标记可信度，缺数据时明确降级，
绝不静默退回一个语义不同的字段（这是 2026-09 基准价退化事故的根因）。

统一字段（对外契约）
--------------------
  price        在售价：BUFF 口径的「在售最低价」，单位元
  ref_price    基准价：用于计算一切跨平台溢价的锚。**永远不含低端档位价**
  buy          求购价（BUFF 口径）
  sell_num     在售挂单数
  buy_num      求购挂单数
  supply       存世量（估算）
  rarity       稀有度（中文档位）
  m1/m7/m30    1/7/30 日涨跌幅（%）
  platforms    10 平台价字典 {平台: 价}

来源与可信度
------------
  _src  = {字段名: 来源名}   来源名 ∈ eco / steamdt / csqaq / firepulse / derived
  _conf = {字段名: 0-100}    对「在售价」类字段，多源一致时高、单源时中、冲突时低
"""
import math

# 已知平台名 → 归一化（用于 cross-source 比较）
_PLAT_ALIAS = {
    'BUFF': 'buff', 'UUYP': 'yyyp', 'YOUPIN': 'yyyp',
    'C5': 'c5', 'IGXE': 'igxe', 'STEAM': 'steam',
}

# 稀有度档位（由高到低），用于评分与展示
_RARITY_ORDER = ('极为罕见', '隐秘', '保密', '罕见', '受限', '军规级', '工业级', '消费级')


def _f(v):
    """安全转 float；无法解析返回 0.0"""
    try:
        if v is None:
            return 0.0
        s = str(v).strip()
        if s in ('', 'None', 'nan'):
            return 0.0
        return float(s)
    except Exception:
        return 0.0


def _nz(*vals):
    """返回第一个 >0 的值，找不到返回 0.0"""
    for v in vals:
        x = _f(v)
        if x > 0:
            return x
    return 0.0


def cross_validate(*pairs, tol=0.12):
    """交叉验证取中位。

    pairs: [(值, 来源名), ...]  只计入值 > 0 的项。
    返回 (最终值, 来源名, 一致性 0-1, 是否冲突)

    - 只有 1 个源        → 直接采用，一致性 0.6（单源不可交叉）
    - 2 个源且相对差≤tol → 取中位（两者均值），一致性 0.95
    - 2 个源且相对差>tol → 取较小的那个（买价保守），一致性 0.3，标记冲突
    - ≥3 个源            → 去掉最高最低后取中位，一致性按离散度算
    """
    vals = [(float(v), str(s)) for v, s in pairs if _f(v) > 0]
    if not vals:
        return 0.0, '', 0.0, False

    if len(vals) == 1:
        return vals[0][0], vals[0][1], 0.6, False

    nums = sorted(v for v, _ in vals)

    if len(nums) == 2:
        a, b = nums
        rel = abs(a - b) / max(a, b) if max(a, b) > 0 else 0
        if rel <= tol:
            mid = (a + b) / 2
            # 来源取更接近中位的那个，便于溯源
            src = min(vals, key=lambda t: abs(t[0] - mid))[1]
            return mid, src, 0.95, False
        # 冲突：取低价（保守，避免高估资产）
        return a, min(vals, key=lambda t: t[0])[1], 0.3, True

    # ≥3 源：去掉极值取中位
    core = nums[1:-1]
    mid = core[len(core) // 2] if core else nums[len(nums) // 2]
    spread = (nums[-1] - nums[0]) / max(nums[-1], 1)
    conf = max(0.2, min(0.98, 1.0 - spread))
    src = min(vals, key=lambda t: abs(t[0] - mid))[1]
    return mid, src, conf, spread > tol


def normalize(item, fp=None, src_hint=None):
    """把一条原始记录归一化成统一字段。

    item    : eco_tracked.json / market.json 的一条（ECO/SteamDT/CSQAQ 混写字段）
    fp      : FirePulse 字段字典（可选）。**若省略，会自动从 item 里抽取 `fp_` 前缀字段**，
              因此调用方可以直接 `normalize(it)` 而不必手动拆分。
    src_hint: 预留，标记本条的主要来源

    返回 (unified_dict, meta_dict)
      unified_dict 只有统一字段名，上层直接用
      meta_dict    含 _src / _conf / _warn / _cov（覆盖率）
    """
    # 自动吸收行内的 fp_* 字段（market.json 的推荐条目就是这么存的）
    if fp is None:
        fp = {k: v for k, v in item.items() if k.startswith('fp_')}
    else:
        merged = {k: v for k, v in item.items() if k.startswith('fp_')}
        merged.update(fp)
        fp = merged
    eco_price = _f(item.get('Price'))                 # ⚠ 低端档位价，绝不可作基准
    eco_plat = _f(item.get('eco_platform_price'))     # ECO 在 10 平台体系的在售均价
    eco_compre = _f(item.get('MarketComprePrice'))    # ECO 综合价
    eco_qg = _f(item.get('QGMaxPrice'))               # ECO 求购价
    eco_sell_total = _f(item.get('SellingTotal'))     # ECO 在售总数（≈存世量）
    eco_max = _f(item.get('MaxPrice'))

    sd_sell = _f(item.get('buff_sell'))               # SteamDT：优先 BUFF，缺失时降级其它平台
    sd_buy = _f(item.get('buff_buy'))
    sd_sell_num = _f(item.get('buff_sell_num'))
    sd_buy_num = _f(item.get('buff_buy_num'))
    sd_source = str(item.get('buff_source') or '').strip()
    yyyp_sell = _f(item.get('yyyp_sell'))
    yyyp_buy = _f(item.get('yyyp_buy'))
    yyyp_sell_num = _f(item.get('yyyp_sell_num'))
    yyyp_buy_num = _f(item.get('yyyp_buy_num'))
    igxe_sell = _f(item.get('igxe_sell'))

    # SteamDT 的 buff_sell 若来源不是 BUFF，则不能当作 BUFF 价参与交叉验证
    sd_is_buff = (sd_source.upper() in ('', 'BUFF'))

    src, conf, warn = {}, {}, []

    # ── 1. 在售价（BUFF 口径）：SteamDT 与 CSQAQ 交叉验证 ──
    #
    # 现状：update.py 里 CSQAQ 先写 item['buff_sell']，SteamDT 后写把它覆盖了，
    #       所以到这一层已经分不出谁是谁。为了恢复交叉验证能力，
    #       约定 callers 可传入原始双源值：item['_csqaq_buff'] / item['_steamdt_buff']。
    #       未提供时退化为单源，confidence 降到 0.6 并记 warn。
    cq_sell = _f(item.get('_csqaq_buff'))
    sd_sell_raw = _f(item.get('_steamdt_buff'))

    if cq_sell > 0 and sd_sell_raw > 0:
        # 真·双源交叉验证
        price, p_src, p_conf, p_conflict = cross_validate(
            (sd_sell_raw, 'steamdt'), (cq_sell, 'csqaq'), tol=0.12)
        if p_conflict:
            warn.append('在售价双源分歧>12%%(steamdt=%.1f vs csqaq=%.1f)' % (sd_sell_raw, cq_sell))
    elif sd_sell > 0:
        price, p_src, p_conf = sd_sell, ('steamdt' if sd_is_buff else (sd_source or 'steamdt').lower()), 0.6
    elif cq_sell > 0:
        price, p_src, p_conf = cq_sell, 'csqaq', 0.6
    else:
        price, p_src, p_conf = 0.0, '', 0.0

    if price > 0:
        src['price'] = p_src
        conf['price'] = round(p_conf, 2)

    # ── 2. 基准价 ref_price：必须是「与 BUFF 非同源」的市场，否则溢价恒为 0 ──
    #
    # ⚠ 血泪教训（2026-09-14 复核）：
    #   最初我用 [buff_sell, yyyp_sell] 的中位当基准。实测 4714/4805 条两者都有值，
    #   但 BUFF 与悠悠是**同市场同口径**、价差常年在 1-2%，
    #   于是 median ≈ buff_sell，premium_buff 恒等于 ±0.x% —— 这是个假指标！
    # 正确做法：基准只取真正独立的市场。优先级：
    #   1) eco_platform_price  (ECO 在 10 平台体系的独立均价)
    #   2) steam_sell          (Steam 社区市场，与国内平台定价逻辑不同)
    #   3) 若都没有 → ref=0，明确标记「无法评估溢价」，**绝不**退回同源价凑数
    ref, ref_src, ref_conf = 0.0, '', 0.0
    steam_sell = _f(item.get('steam_sell'))
    if eco_plat > 0:
        ref, ref_src, ref_conf = eco_plat, 'eco', 0.75
        # 若同源有 Steam 价，可交叉验证（两者是可比的「独立市场」）
        if steam_sell > 0:
            ref, ref_src, ref_conf, cf = cross_validate(
                (eco_plat, 'eco'), (steam_sell, 'csqaq'), tol=0.35)
            if cf:
                warn.append('基准价分歧>35%%(eco=%.1f vs steam=%.1f)' % (eco_plat, steam_sell))
    elif steam_sell > 0:
        ref, ref_src, ref_conf = steam_sell, 'csqaq', 0.6
    else:
        # 只有国内平台价 → 无法构成有意义的跨市场溢价
        warn.append('无独立市场基准，溢价不可评估')
    # 若以上全无 → ref 保持 0，上层应判为「无法评估溢价」而非编造

    if ref > 0:
        src['ref_price'] = ref_src
        conf['ref_price'] = round(ref_conf, 2)

    # ── 3. 求购 ──
    buy = _nz(sd_buy, eco_qg)
    if buy > 0:
        src['buy'] = 'steamdt' if sd_buy > 0 else 'eco'
        conf['buy'] = 0.9 if sd_buy > 0 else 0.6

    # ── 4. 挂单数 ──
    sell_num = _nz(sd_sell_num, eco_sell_total)
    if sell_num > 0:
        src['sell_num'] = 'steamdt' if sd_sell_num > 0 else 'eco'
    buy_num = _nz(sd_buy_num)
    if buy_num > 0:
        src['buy_num'] = 'steamdt'

    # ── 5. 存世量：优先ECO在售总数，其次 FirePulse ──
    supply = _nz(eco_sell_total, fp.get('fp_total_supply'))
    if supply > 0:
        src['supply'] = 'eco' if eco_sell_total > 0 else 'firepulse'
        conf['supply'] = 0.8 if eco_sell_total > 0 else 0.7

    # ── 6. 稀有度 ──
    rarity = str(fp.get('fp_rarity') or '').strip()
    if rarity:
        src['rarity'] = 'firepulse'

    # ── 7. 趋势（1/7/30 日）──
    trend = {}
    for key, fp_key in (('m1', 'fp_today_ratio'), ('m7', 'fp_week_ratio'), ('m30', 'fp_month_ratio')):
        try:
            v = float(fp.get(fp_key))
            trend[key] = v
            src[key] = 'firepulse'
        except Exception:
            trend[key] = None
    if trend.get('m1') is None:
        v = _f(item.get('rate_1'))
        if v:
            trend['m1'] = v
            src['m1'] = 'csqaq'

    # ── 8. 10 平台价字典 ──
    platforms = {}
    plat_obj = item.get('platforms')
    if isinstance(plat_obj, dict):
        for k, v in plat_obj.items():
            key = _PLAT_ALIAS.get(str(k).upper(), str(k).lower())
            x = _f(v)
            if x > 0:
                platforms[key] = x
    for nm, v in (('buff', sd_sell), ('yyyp', yyyp_sell), ('igxe', igxe_sell),
                  ('steam', steam_sell)):
        if v > 0 and nm not in platforms:
            platforms[nm] = v
    if platforms:
        src['platforms'] = 'steamdt' if sd_sell > 0 else ('csqaq' if yyyp_sell > 0 else 'eco')

    # ── 9. Steam 独立市场价（目前 CSQAQ 提供但 update.py 未持久化）──
    steam_val = steam_sell
    if steam_val > 0:
        src['steam_sell'] = 'csqaq'
        conf['steam_sell'] = 0.7

    # ── 组装 ──
    unified = {
        'price': round(price, 2) if price > 0 else 0.0,
        'ref_price': round(ref, 2) if ref > 0 else 0.0,
        'buy': round(buy, 2) if buy > 0 else 0.0,
        'sell_num': int(sell_num) if sell_num > 0 else 0,
        'buy_num': int(buy_num) if buy_num > 0 else 0,
        'supply': int(supply) if supply > 0 else 0,
        'rarity': rarity,
        'm1': trend.get('m1'),
        'm7': trend.get('m7'),
        'm30': trend.get('m30'),
        'platforms': platforms,
        'steam_sell': round(steam_val, 2) if steam_val > 0 else 0.0,
        # ── 溢价：一律基于 ref_price，无独立市场基准时为 None（明确不可评估）──
        'premium_buff': None,
        'premium_yyyp': None,
        'premium_igxe': None,
        'premium_liquid': None,
    }
    if ref > 0:
        if sd_sell > 0:
            unified['premium_buff'] = round((sd_sell - ref) / ref * 100, 1)
        if yyyp_sell > 0:
            unified['premium_yyyp'] = round((yyyp_sell - ref) / ref * 100, 1)
        if igxe_sell > 0:
            unified['premium_igxe'] = round((igxe_sell - ref) / ref * 100, 1)
        # 「国内最优平台 vs 独立市场」的价差：真正有交易意义的信号
        liq = [v for v in (sd_sell, yyyp_sell) if v > 0]
        if liq:
            unified['premium_liquid'] = round((min(liq) - ref) / ref * 100, 1)

    # 覆盖率：核心字段有多少拿到了
    core = ('price', 'ref_price', 'buy', 'sell_num', 'supply', 'rarity', 'm7', 'platforms', 'steam_sell')
    got = sum(1 for k in core if unified.get(k) not in (None, '', 0, 0.0, {}))
    meta = {
        '_src': src,
        '_conf': conf,
        '_warn': warn,
        '_cov': round(got / len(core), 2),
    }
    return unified, meta


def coverage_report(items, fp_map=None):
    """统计一批数据的字段覆盖率，用于监控数据质量。

    fp_map: {hash_name: fp_dict}，可选。未提供时依赖 item 行内的 fp_* 字段。
    """
    n = len(items)
    if n == 0:
        return {}
    keys = ('price', 'ref_price', 'buy', 'sell_num', 'buy_num', 'supply', 'rarity', 'm7', 'platforms', 'steam_sell')
    hit = {k: 0 for k in keys}
    warn_cnt = 0
    for it in items:
        hn = it.get('HashName') or it.get('hash_name') or ''
        fp = (fp_map or {}).get(hn)
        u, m = normalize(it, fp=fp)
        for k in keys:
            if u.get(k) not in (None, '', 0, 0.0, {}):
                hit[k] += 1
        if m['_warn']:
            warn_cnt += 1
    out = {k: round(v / n * 100, 1) for k, v in hit.items()}
    out['_warn_pct'] = round(warn_cnt / n * 100, 1)
    out['_n'] = n
    return out


def apply_to_item(item, fp=None):
    """把归一化结果**就地回写**到原 item 上，供 update.py 平滑接入。

    写入的字段名（统一契约，上层后续只用这些）：
      n_price / n_ref / n_buy / n_sell_num / n_buy_num
      n_supply / n_rarity / n_m7 / n_m30
      n_premium_buff / n_premium_yyyp / n_premium_igxe / n_premium_liquid
      n_steam / n_cov / n_src / n_conf / n_warn

    用 n_ 前缀避免与原有字段冲突，老代码可继续读老字段，新功能读 n_ 字段。
    """
    u, m = normalize(item, fp=fp)
    item['n_price'] = u['price']
    item['n_ref'] = u['ref_price']
    item['n_buy'] = u['buy']
    item['n_sell_num'] = u['sell_num']
    item['n_buy_num'] = u['buy_num']
    item['n_supply'] = u['supply']
    item['n_rarity'] = u['rarity']
    item['n_m1'] = u['m1']
    item['n_m7'] = u['m7']
    item['n_m30'] = u['m30']
    item['n_steam'] = u['steam_sell']
    item['n_premium_buff'] = u['premium_buff']
    item['n_premium_yyyp'] = u['premium_yyyp']
    item['n_premium_igxe'] = u['premium_igxe']
    item['n_premium_liquid'] = u['premium_liquid']
    item['n_platforms'] = u['platforms']
    item['n_cov'] = m['_cov']
    item['n_src'] = m['_src']
    item['n_conf'] = m['_conf']
    item['n_warn'] = m['_warn']
    return item


if __name__ == '__main__':
    import io
    import json
    import os
    import sys

    HERE = os.path.dirname(os.path.abspath(__file__))

    # ── 单元自检：确认「同源价不能当基准」这条红线守住了 ──
    if '--self-test' in sys.argv:
        print('=== 归一化层 单元自检 ===')
        cases = [
            ('同源价不应产生溢价', {
                'buff_sell': '100', 'yyyp_sell': '101',
            }, None, {'ref_price': 0.0, 'premium_buff': None}),
            ('有独立市场价应能算溢价', {
                'buff_sell': '80', 'eco_platform_price': '100',
            }, None, {'ref_price': 100.0, 'premium_buff': -20.0}),
            ('低端档位价绝不可作基准', {
                'Price': '45.71', 'buff_sell': '65.8',
            }, None, {'ref_price': 0.0}),
            ('双源一致才给高可信', {
                '_steamdt_buff': '100', '_csqaq_buff': '100.5',
            }, None, {'price': 100.25, 'conf': 0.95}),
            ('双源冲突取低价并告警', {
                '_steamdt_buff': '100', '_csqaq_buff': '200',
            }, None, {'price': 100.0, 'warn': True}),
        ]
        fails = 0
        for name, it, fp, expect in cases:
            u, m = normalize(it, fp=fp)
            ok = True
            detail = []
            if 'ref_price' in expect and abs(u['ref_price'] - expect['ref_price']) > 0.01:
                ok = False
                detail.append('ref_price=%s 期望 %s' % (u['ref_price'], expect['ref_price']))
            if 'premium_buff' in expect and u['premium_buff'] != expect['premium_buff']:
                ok = False
                detail.append('premium_buff=%s 期望 %s' % (u['premium_buff'], expect['premium_buff']))
            if 'price' in expect:
                if abs(u['price'] - expect['price']) > 0.01:
                    ok = False
                    detail.append('price=%s 期望 %s' % (u['price'], expect['price']))
                if 'conf' in expect and abs(m['_conf'].get('price', 0) - expect['conf']) > 0.01:
                    ok = False
                    detail.append('conf=%s 期望 %s' % (m['_conf'].get('price'), expect['conf']))
            if expect.get('warn') and not m['_warn']:
                ok = False
                detail.append('应产生告警但没有')
            print('  [%s] %s%s' % ('OK' if ok else 'FAIL', name,
                                   ('  -> ' + '; '.join(detail)) if detail else ''))
            if not ok:
                fails += 1
        print()
        print('自检结果: %s (%d/%d)' % ('全部通过' if fails == 0 else '有失败', len(cases) - fails, len(cases)))
        sys.exit(0 if fails == 0 else 1)

    path = os.path.join(HERE, 'eco_tracked.json')
    if not os.path.exists(path):
        print('eco_tracked.json not found'); sys.exit(1)
    data = json.load(io.open(path, encoding='utf-8'))
    print('=== 归一化层自检 ===')
    print('样本数:', len(data))
    rep = coverage_report(data)
    print('\n字段覆盖率:')
    for k, v in rep.items():
        print('  %-14s %s' % (k, v))
    print('\n--- 抽样 5 条 ---')
    for it in data[:5]:
        u, m = normalize(it)
        print('\n%s' % (it.get('GoodsName') or it.get('HashName'))[:60])
        print('  price=%.2f (src=%s)' % (u['price'], m['_src'].get('price', '-')))
        print('  ref  =%.2f (src=%s)' % (u['ref_price'], m['_src'].get('ref_price', '-')))
        print('  premium_buff=%s  supply=%d  rarity=%s  cov=%.2f' % (
            u['premium_buff'], u['supply'], u['rarity'] or '-', m['_cov']))
        if m['_warn']:
            print('  WARN:', '; '.join(m['_warn']))