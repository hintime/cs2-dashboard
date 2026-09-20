#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""饰品筛选规则 —— **单一来源**，采集 / 扫描 / 异动三处共用。

为什么要有这个文件
------------------
原来筛选逻辑散在两处，且**互不一致**：
  · `generate_scan.py` 有一套（SKIP_CATS + _is_valid_scan_item）—— 只作用在 market_scan.json
  · `update.py` 另有一套（_EXCLUDE_PREFIXES + _EXCLUDE_EXTERIORS）—— 只作用在推荐池
  · 而**数据库写入**和**异动榜**两处**完全没过滤**

结果（2026-09-20 实测）：db 里躺着 811 个本不该在的标的（15.5%），
其中 575 个 StatTrak、188 个战痕/破损、54 个被误判成探员的贴纸胶囊。

排除范围（义轩 2026-09-20 确认）
--------------------------------
  ✔ 排除：StatTrak™ / Souvenir 前缀
  ✔ 排除：战痕累累(BS) / 破损不堪(WW)
  ✔ 排除：贴纸、箱子、胶囊、布章、挂件、涂鸦、音乐盒
  ✘ 保留：**探员（agent）** —— 虽然不在原有排除列表里，但它有交易价值

★ 关于"贴纸胶囊被误判成探员"这个 bug
------------------------------------
`2021 Community Sticker Capsule` 这类名字：不含磨损词、前缀也不是武器，
于是落到了 agent 分支，而 agent 不在 SKIP_CATS 里 → 直接漏网。

修法是加两条**精确**判断（放在 agent 分支之前）：
  1. 含 `Capsule` → case
  2. 含贴纸专属后缀 `(Holo-Foil)` / `(Foil)` / `(Holo)` / `(Glitter)` / `(Lenticular)` → sticker
武器与刀不会有这些后缀，所以**不会误伤**。
"""

import re

# 这些品类整类排除
SKIP_CATS = {'sticker', 'musickit', 'patch', 'case', 'charm', 'graffiti'}
# 这些品类保留
KEEP_CATS = {'weapon', 'knife', 'glove', 'agent'}

EXCLUDE_PREFIXES = ('StatTrak', 'Souvenir')
EXCLUDE_EXTERIORS = ('Battle-Scarred', 'Well-Worn',
                     '战痕累累', '破损不堪')

# 贴纸专属后缀（武器/刀不会有）
STICKER_MARKS = ('(Holo-Foil)', '(Foil)', '(Holo)', '(Glitter)', '(Lenticular)')
# 胶囊
CAPSULE_MARKS = ('Capsule',)

# 终端机 / 武器箱等"无意义"标的（沿用原 generate_scan 的判断）
BORING_MARKS = ('Terminal', 'Souvenir Package')

_GLOVE_MARKS = ('Gloves', 'Hand Wraps', 'Sport Gloves', 'Specialist Gloves',
                'Moto Gloves', 'Driver Gloves', 'Bloodhound Gloves',
                'Hydra Gloves', 'Broken Fang Gloves')
# ★ 刀名识别：很多刀的名字**不含 "Knife"**（Karambit / Bayonet / Talon ...），
#   原来只判 `'Knife' in hn`，导致爪刀等被误归为 weapon。
_KNIFE_MARKS = ('Knife', 'Karambit', 'Bayonet', 'Daggers', 'Kukri', 'Skeleton',
                'Nomad', 'Paracord', 'Survival', 'Ursus', 'Navaja', 'Stiletto',
                'Talon', 'Falchion', 'Bowie', 'Huntsman', 'Butterfly', 'Shadow Daggers')
_WEAR_WORDS = ('Factory New', 'Minimal Wear', 'Field-Tested', 'Well-Worn',
               'Battle-Scarred', '崭新出厂', '略有磨损', '久经沙场',
               '破损不堪', '战痕累累')
_WEAPON_PREFIXES = (
    'AK-47', 'M4A4', 'M4A1-S', 'AWP', 'AUG', 'SG ', 'FAMAS', 'Galil', 'SSG',
    'SCAR', 'G3SG1', 'P250', 'P2000', 'USP', 'Glock', 'Desert Eagle',
    'Five-SeveN', 'CZ75', 'Dual Berettas', 'R8', 'Tec-9',
    'MP5', 'MP7', 'MP9', 'MAC-10', 'PP-', 'UMP', 'P90',
    'Nova', 'XM1014', 'MAG-7', 'Sawed-Off', 'Negev', 'M249',
    'Zeus', 'Flashbang', 'Smoke', 'HE Grenade', 'Molotov', 'Incendiary',
    'Decoy', '★')


def classify(hn):
    """判定品类。返回 sticker/case/patch/charm/graffiti/musickit/
    weapon/knife/glove/agent/other。

    ★ 判断顺序很关键（2026-09-20 踩坑）：
      必须**先认「有磨损词的皮肤」**，再判箱子/挂件。否则会被皮肤名误伤：
        · `★ Ursus Knife | Case Hardened (Factory New)`
            —— "Case Hardened"(表面淬火) 含 "Case" → 被误判成箱子
        · `★ Sport Gloves | Creme Pinstripe (Minimal Wear)`
            —— "Pinstripe"(细条纹) 含 "Pin" → 被误判成挂件
      两者合计误杀约 51 件真品。判据：**皮肤一定有「 | 」+ 磨损词**。
    """
    if not hn:
        return 'other'

    # ── 1) 贴纸专属后缀（武器/刀绝不会有这些后缀，可放心最高优先）──
    if any(m in hn for m in STICKER_MARKS):
        return 'sticker'
    if hn.startswith('Sticker'):
        return 'sticker'

    has_sep = ' | ' in hn
    has_wear = any(w in hn for w in _WEAR_WORDS)

    # ── 2) 皮肤类：有「 | 」且带磨损词 —— 一定是武器/刀/手套 ──
    if has_sep and has_wear:
        if any(k in hn for k in _KNIFE_MARKS):
            return 'knife'
        if any(g in hn for g in _GLOVE_MARKS):
            return 'glove'
        return 'weapon'

    # ── 3) 无磨损词的，才可能是箱子/胶囊/音乐盒/挂件等 ──
    if any(m in hn for m in CAPSULE_MARKS):
        return 'case'
    if hn.endswith('Case') or any(c in hn for c in ('Container', 'Package')):
        return 'case'
    if 'Music Kit' in hn or 'musickit' in hn.lower():
        return 'musickit'
    if 'Graffiti' in hn:
        return 'graffiti'
    if 'Patch' in hn:
        return 'patch'
    if any(c in hn for c in ('Charm', 'Pin')):
        return 'charm'

    if any(b in hn for b in BORING_MARKS):
        return 'other'

    # 无磨损词的刀/手套（少数数据缺失）
    if any(k in hn for k in _KNIFE_MARKS):
        return 'knife'
    if any(g in hn for g in _GLOVE_MARKS):
        return 'glove'

    # ── 4) 探员：形如 "Name | Team"（有分隔符但无磨损词）──
    if has_sep:
        return 'agent'

    # ── 5) 剩下的看前缀是不是武器 ──
    pref = hn.split('|')[0].strip()
    if any(pref.startswith(p) or p in pref for p in _WEAPON_PREFIXES):
        return 'weapon'
    return 'other'


def is_excluded(hn, goods_name=''):
    """是否应被排除（不采集 / 不入异动榜）。

    ★ 采集层与展示层共用这一个函数，避免规则漂移。
    """
    if not hn:
        return True
    full = hn + (goods_name or '')

    # 前缀。⚠ 必须用 `in` 而不是 `startswith`：
    #   刀的名字形如 `★ StatTrak™ Ursus Knife | ...`，**以「★ 」开头**，
    #   用 startswith('StatTrak') 会整批漏掉（2026-09-20 实测漏 1043 个）。
    #   ⚠ 还要**大小写不敏感** —— 数据里存在 `_stattrak_` 这种小写内部 ID。
    hn_l = hn.lower()
    if any(p.lower() in hn_l for p in EXCLUDE_PREFIXES):
        return True
    # 磨损
    if any(e in full for e in EXCLUDE_EXTERIORS):
        return True
    # 品类
    c = classify(hn)
    if c in SKIP_CATS:
        return True
    if c not in KEEP_CATS:
        return True
    return False


if __name__ == '__main__':
    # 自检
    CASES = [
        ('AK-47 | Redline (Field-Tested)', False, 'weapon'),
        ('★ Butterfly Knife | Doppler (Factory New)', False, 'knife'),
        ('★ Sport Gloves | Pandora\'s Box (Factory New)', False, 'glove'),
        ('Sir Bloody Miami Darryl | The Professionals', False, 'agent'),
        ('StatTrak™ AK-47 | Redline (Field-Tested)', True, 'weapon'),
        # ★ 回归用例：刀名以「★ 」开头，StatTrak 不在开头 —— 用 startswith 会漏掉
        ('★ StatTrak™ Ursus Knife | Slaughter (Factory New)', True, 'knife'),
        ('★ StatTrak™ Karambit | Scorched (Factory New)', True, 'knife'),
        ('AK-47 | Redline (Battle-Scarred)', True, 'weapon'),
        ('2021 Community Sticker Capsule', True, 'case'),
        ('Berlin 2019 Legends (Holo-Foil)', True, 'sticker'),
        ('Sticker | Titan (Holo) | Katowice 2014', True, 'sticker'),
        ('Operation Riptide Case', True, 'case'),
        ('Music Kit | AWOLNATION, I Am', True, 'musickit'),
        ('Charm | Die-cast AK', True, 'charm'),
        ('Sealed Graffiti | Recoil AK-47', True, 'graffiti'),
        ('Patch | Metal SAS', True, 'patch'),
        ('Souvenir AWP | Dragon Lore (Factory New)', True, 'weapon'),
        # ★ 回归用例 2：皮肤名把品类关键词"吃掉"了 —— 判顺序错了会被误杀
        #   "Case Hardened"(表面淬火) 含 Case，"Pinstripe"(细条纹) 含 Pin
        ('★ Ursus Knife | Case Hardened (Factory New)', False, 'knife'),
        ('★ Butterfly Knife | Case Hardened (Minimal Wear)', False, 'knife'),
        ('★ Sport Gloves | Creme Pinstripe (Minimal Wear)', False, 'glove'),
        ('★ Hand Wraps | Spruce DDPAT (Well-Worn)', True, 'glove'),
        # 真箱子（无 " | " 分隔符）
        ('Operation Riptide Case', True, 'case'),
        ('Chroma 2 Case', True, 'case'),
    ]
    ok = 0
    for hn, exp_excl, exp_cat in CASES:
        c = classify(hn)
        e = is_excluded(hn)
        good = (c == exp_cat and e == exp_excl)
        ok += good
        print("%s %-52s cat=%-10s excl=%-5s (期望 cat=%s excl=%s)"
              % ("✓" if good else "✗", hn[:52], c, e, exp_cat, exp_excl))
    print("\n自检: %d/%d" % (ok, len(CASES)))
