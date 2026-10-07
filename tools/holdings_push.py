# -*- coding: utf-8 -*-
"""持仓一键接收端（服务器侧）。

配合浏览器一键脚本（见index.html 的「⬆ 同步持仓到服务器」按钮）使用：
    浏览器 localStorage 的持仓 → POST /api/holdings-push → 本脚本落盘

为什么需要它（2026-10-07 实测发现）
------------------------------------
系统里其实有**三份**互不同步的持仓数据：
  1. 浏览器 localStorage —— 页面真正显示的那份（义轩手工维护，最准）
  2. CF Worker KV       —— 只存不读回服务器，且实测已44 小时没更新
  3. 服务器 holdings.json —— 采集/价格用，实测只有 32 条（少的 10 条）
而 Worker 的 `/api/holdings-sync` **只写 KV，从不写服务器文件**，
所以服务器的 32 条一直是旧的手工放置版本 —— 今天 42 条持仓里有 10 条
（FN57毛细血管/法玛斯2A2F/格洛克幻影冥魂/P250 等）**服务器从来没见过**，
加密采集也就没覆盖到它们。

⚠⚠ 成本价是红线（本项目硬约束：库存成本价是关键数据不变式）
   合并规则**极其保守**：
     · 服务器已有的条目 → **保留服务器的 cost**，除非浏览器明确带了非 0 成本；
     · 浏览器 cost=0 而服务器有 cost → **用服务器的**（不让 0 覆盖真实成本）；
     · 新增条目（服务器没有）→ 采浏览器的 cost（哪怕是 0）。
   这样既能补齐缺失条目，又**绝不可能因为同步而丢失已有成本价**。

用法（服务器）：
    venv/bin/python tools/holdings_push.py            # 读 stdin 的 JSON
    venv/bin/python tools/holdings_push.py --file x.json
"""
import argparse
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOLD = os.path.join(REPO, 'holdings.json')
BACKUP_DIR = os.path.join(REPO, 'backups', 'holdings')

# 浏览器 localStorage 里可能出现的标识字段（历史包袱，四个都要收）
KEY_FIELDS = ('market_hash', 'mh', 'name_en', 'name', 'n')


def pick_key(it):
    for k in KEY_FIELDS:
        v = it.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ''


def norm_qty(it):
    """取 qty。⚠ 三个case 必须分开，不能都兜成1 或都兜成 0：

       qty 缺失 / 非数字 → 返回 None（**未知**，保持服务器原值不动）
       qty = 0 或负数     → 返回 0（**已卖出**，走卖出记录）
       qty = 正数        → 返回该值

    早先两个 bug 都踩过：
      ① `return q if q > 0 else 1` → 卖出件（qty=0）被变成 qty=1 的**新增**，
         「已卖出」反过来成了「还持有」；
      ② 一律返回 0 → 老数据里没写 qty 的条目会被误判成「全部卖出」而被删掉。
    所以用 None 表达「不知道」，让调用方决定保持原值。
    """
    raw = it.get('qty')
    if raw is None or raw == '':
        return None
    try:
        return int(float(raw))
    except Exception:
        return None


def norm_cost(it):
    try:
        c = float(it.get('cost') or 0)
        return c if c > 0 else 0.0
    except Exception:
        return 0.0


def load_server():
    try:
        with open(HOLD, encoding='utf-8') as f:
            d = json.load(f)
        items = d.get('items') if isinstance(d, dict) else d
        return (d if isinstance(d, dict) else {}), list(items or [])
    except Exception as e:
        print('[PUSH] 读服务器 holdings.json 失败：%s（按空处理）' % e, file=sys.stderr)
        return {}, []


def backup(tag=''):
    if not os.path.exists(HOLD):
        return None
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        p = os.path.join(BACKUP_DIR, 'holdings-%s%s.json'
                         % (time.strftime('%Y%m%d-%H%M%S'), ('-' + tag) if tag else ''))
        with open(HOLD, 'rb') as a, open(p, 'wb') as b:
            b.write(a.read())
        return p
    except Exception as e:
        print('[PUSH] 备份失败：%s（**继续**合并，只是没有回滚点）' % e, file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', help='从文件读；不给则读 stdin')
    ap.add_argument('--dry-run', action='store_true', help='只看会怎么合并，不落盘')
    ap.add_argument('--no-backup', action='store_true')
    args = ap.parse_args()

    raw = open(args.file, encoding='utf-8').read() if args.file else sys.stdin.read()
    try:
        body = json.loads(raw)
    except Exception as e:
        print('[PUSH] JSON 解析失败：%s' % e, file=sys.stderr)
        return 1
    # 允许直接传数组，或 {items:[...]} / {holdings:[...]}
    if isinstance(body, list):
        incoming = body
    elif isinstance(body, dict):
        incoming = body.get('items') or body.get('holdings') or []
    else:
        incoming = []
    if not isinstance(incoming, list) or not incoming:
        print('[PUSH] 没有可用的持仓条目', file=sys.stderr)
        return 1

    # 去重（同 market_hash 后者覆盖前者，浏览器里可能因多设备残留重复）
    # ⚠ 这里产出的是 **dict**（key=market_hash），后面合并要按 key 遍历，
    #   所以不能直接改成 list —— 去重必须在 dict 上做，否则同件两条都会进 holdings。
    seen = {}
    for it in incoming:
        if not isinstance(it, dict):
            continue
        k = pick_key(it)
        if k:
            seen[k] = it
    incoming_map = seen
    incoming = list(seen.values())
    print('[PUSH] 收到 %d 条（去重前 %d）' % (len(incoming), len(incoming)))

    sdoc, sitems = load_server()
    server_map = {}
    for h in sitems:
        k = pick_key(h) if isinstance(h, dict) else ''
        if k:
            server_map[k] = h

    added, updated, cost_kept, cost_new = [], [], 0, 0
    removed = []          # qty<=0 且服务器有此条 → 需从持仓移除
    skipped_sold = []      # qty<=0 但服务器本就没这条 → 无需动
    merged = []
    for it in sitems:
        merged.append(dict(it) if isinstance(it, dict) else it)

    for k, it in incoming_map.items():
        c = norm_cost(it)
        q = norm_qty(it)
        sv = server_map.get(k)

        # ── 卖出：qty 明确为 0/负数 ──
        #   ⚠ 无论服务器有没有这条，都不能进持仓。
        #     服务器没有 → 直接忽略（本来就不在持仓里，无需移除）。
        if q is not None and q <= 0:
            if sv is not None:
                removed.append(k)
            else:
                skipped_sold.append(k)
            continue

        # ── qty 未知（字段缺失）：保持服务器原值，只补价格类字段 ──
        if q is None and sv is not None:
            for f in ('name', 'wear', 'category'):
                if it.get(f) and not sv.get(f):
                    sv[f] = it[f]
            updated.append(k)
            continue

        if sv is None:
            # 新增：服务器没见过这条。qty 未知时按 1（浏览器没写就当1 件）
            rec = {
                'market_hash': k,
                'name': it.get('name') or it.get('n') or '',
                'cost': c,
                'qty': q if (q is not None and q > 0) else 1,
                'wear': (it.get('wear') or ''),
                'category': (it.get('category') or ''),
            }
            merged.append(rec)
            added.append(k)
            if c > 0:
                cost_new += 1
            continue
        # 已存在：**只在新 cost>0 且旧 cost==0 时才补成本**，否则一律保留旧值。
        # ⚠ 这是成本价红线的核心：绝不允许「0 覆盖真实成本」。
        if c > 0 and norm_cost(sv) <= 0:
            sv['cost'] = c
            cost_kept += 1
        # qty 以浏览器为准（它是义轩手工维护的主数据）；未知则保持原值
        if q is not None:
            sv['qty'] = q
        for f in ('name', 'wear', 'category'):
            if it.get(f) and not sv.get(f):
                sv[f] = it[f]
        updated.append(k)

    # 服务器侧兜底剔除：qty<=0 的条目不进持仓。
    # ⚠ 必须 `h.get('qty') is not None` 才判 —— 老的条目可能没写 qty 字段，
    #   直接 int(...) 会走 except 保留（正确）；但如果写成
    #   `int(float(h.get('qty') or 1))` 就会把「没写 qty」当成 1 件，
    #   而如果写成 `or 0` 又会把「没写 qty」当成已卖出而删掉。两种都错。
    kept, dropped = [], []
    for h in merged:
        raw = h.get('qty') if isinstance(h, dict) else None
        if raw is not None:
            try:
                if int(float(raw)) <= 0:
                    dropped.append(h.get('market_hash') or h.get('name') or '')
                    continue
            except Exception:
                pass
        kept.append(h)
    for d in dropped:
        if d not in removed:
            removed.append(d)

    print('[PUSH] 合并结果：新增 %d / 更新 %d / 移除(qty<=0) %d / 卖出但服务器本就没有 %d 条'
          % (len(added), len(updated), len(removed), len(skipped_sold)))
    print('[PUSH] 成本处理：补写 %d 条（服务器原有成本一律保留，0 不覆盖）' % cost_kept)
    print('[PUSH] 新增条目里带成本的：%d' % cost_new)
    if added:
        print('[PUSH] 新增前 8 条：')
        for k in added[:8]:
            print('        %s' % k[:60])
    if removed:
        print('[PUSH] 被移除（qty<=0，视作卖出）：')
        for k in removed[:10]:
            print('        %s' % k[:60])

    if args.dry_run:
        print('[PUSH] dry-run，未落盘')
        return 0

    if not args.no_backup:
        b = backup('prepush')
        if b:
            print('[PUSH] 已备份 -> %s' % os.path.relpath(b, REPO))

    # 保留原有的元数据字段，合并 items
    doc = dict(sdoc) if isinstance(sdoc, dict) else {}
    doc['items'] = kept
    doc['update_time'] = time.strftime('%Y-%m-%d %H:%M:%S')
    doc['total_cost'] = round(sum(
        float(h.get('cost') or 0) * int(float(h.get('qty') or 1)) for h in kept), 2)
    doc['total_qty'] = sum(int(float(h.get('qty') or 1)) for h in kept)
    doc['source'] = 'holdings_push.py（浏览器 localStorage 同步）'
    tmp = HOLD + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    os.replace(tmp, HOLD)      # 原子替换，避免读到半截文件
    try:
        os.chmod(HOLD, 0o600)
    except Exception:
        pass
    print('[PUSH] 已写入 %s：%d 条 / qty %d / 成本合计 ¥%.2f'
          % (os.path.basename(HOLD), len(kept), doc['total_qty'], doc['total_cost']))
    if removed:
        print('[PUSH] ⚠ 移除的 %d 条请手工确认是否真的卖出：%s'
              % (len(removed), '、'.join(x[:30] for x in removed[:5])))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)