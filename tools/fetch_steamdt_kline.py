# -*- coding: utf-8 -*-
"""SteamDT 官方 K 线拉取器 —— 生成 kline_sd.json（小时K / 日K / 周K）。

为什么要有这个（2026-10-07）
------------------------------
自采的K 线有两个硬伤（都是实测的，不是推测）：
  1. **1 小时 K 做不出来**：cron 的 prices 轮只在 :00/:30 跑、history 轮只在
     每小时 :15 跑 → 每小时只有 1 个采样点 → 96.1% 的小时桶只有 1 个点
     → open=high=low=close，影线完全退化。所以最小粒度只能退到 2 小时。
  2. **历史太短**：库里最早 2026-07-08，58 天。日K 只到 58 天、周K 只 12 周。

SteamDT 官方接口直接给成品 OHLC，实测（type=1/2/3）：
     1 小时  90 天  2160 根（每天 24 根，整点对齐）
     日      365 天  365 根
     周      4.3 年  224 根（回溯到 2022 年）
所以小时 K 只能靠它 —— CSQAQ 那边做不到（实测它每天只有 6 个点）。

⚠ 字段顺序坑（2026-10-07 实测确认）
   官方返回 `[ts, open, close, high, low]` —— **close 在 high/low 前面**，
   不是常见的 [ts,o,h,l,c]。写错的话影线方向会反。
   本脚本已用不变量校验过：`h >= max(o,c)` 且 `l <= min(o,c)`，
   对官方真实数据 4/4 成立、错映射 4/4 失败 —— 映射是 [ts,o,c,h,l]。

⚠ 价格口径：platform 参数选 BUFF
   实测同一件 FAMAS | Commemoration 官方四个平台的日K 差异很大：
       BUFF   ~359~ 380
       ALL    ~354 ~ 376
       YOUPIN ~354 ~ 376
       STEAM  ~460 ~ 534   ← Steam 手续费高，天然贵 30%+
   我们自采是「eco 优先、buff 兜底」，与 BUFF 口径最接近，所以选 BUFF。

限频：官方 120 次/分钟、4000 次/天。本脚本单件三档 = 3 次请求，
     32 件持仓 = 96 次；按 0.5 秒/次节流约需 50 秒，离上限极远。

用法（服务器）：
    venv/bin/python tools/fetch_steamdt_kline.py
    venv/bin/python tools/fetch_steamdt_kline.py --limit-items 200 --no-push
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_ENV = 'STEAMDT_KEY'
API_URL = 'https://open.steamdt.com/open/cs2/item/v1/kline'

# type -> (输出文件, 标签, 单位, 官方粒度说明)
GRANS = {
    '1h': {'type': 1, 'file': 'kline_sd_1h.json', 'label': '1小时K', 'unit': '根'},
    '1d': {'type': 2, 'file': 'kline_sd_1d.json', 'label': '日K', 'unit': '天'},
    '1w': {'type': 3, 'file': 'kline_sd_1w.json', 'label': '周K', 'unit': '周'},
}
# 每档保留的最大根数。⚠ 体积是这个脚本的主要约束（实测 151 件）：
#     1h:官方90天=每件2160 根 -> 全给是 5.4MB，光这一档就吃掉首屏预算；
#         200根 ≈ 8 天，够看日内波动；更长区间交给日K/2小时K。
#     1d: 官方365 天 -> 4.33MB。240根 ≈ 8 个月，够看趋势了
#         （要再看远就切周K，周档有 4.3 年）。
#     1w: 官方 4.3 年 224 根 -> 2.36MB，保留全部（一年才 52 根，很划算）。
#   前端每档按需加载，用户通常只看一档，所以单档控制在 1MB 上下比较合适。
MAX_BARS = {'1h': 200, '1d': 240, '1w': 260}
# 请求节流（秒）。官方限频 120/分钟 → 0.5s 已是安全线（120/分钟）的两倍余量
THROTTLE = 0.5
PLATFORM = 'BUFF'


def read_key():
    """从环境变量或 local_keys.env 读 STEAMDT_KEY。"""
    k = os.environ.get(KEY_ENV, '')
    if k:
        return k.strip()
    try:
        with open(os.path.join(REPO, 'local_keys.env'), encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('export '):
                    line = line[len('export '):].strip()
                if line.startswith(KEY_ENV + '=') or line.startswith(KEY_ENV + ' '):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ''


def load_holdings_keys():
    """持仓标识（强制 100% 覆盖）+ 追踪池标识（按活跃度补量）。"""
    hold = []
    p = os.path.join(REPO, 'holdings.json')
    try:
        with open(p, encoding='utf-8') as f:
            d = json.load(f)
        items = d.get('items') or d.get('holdings') or (d if isinstance(d, list) else [])
        for h in items:
            if not isinstance(h, dict):
                continue
            for k in ('market_hash', 'mh', 'name_en', 'name', 'n'):
                v = h.get(k)
                if v:
                    hold.append(v)
                    break
    except Exception as e:
        print('提示：读不到 holdings.json（%s）' % e)
    return hold


def load_track_keys(limit):
    """追踪池标识。⚠ 只作为补量 —— 官方是**按单品查询**的，全站 5189 件要
    5189 次/档 × 3 档 = 15567 次，远超官方 4000 次/天 的额度，必须限量。

    ⚠ 字段名坑（2026-10-07 实测）：eco_tracked.json 的元素用 **HashName**
      （大写 H），不是 hash_name；market.json 是 dict 套list，
      标识在 items[i].hash_name。早先只写了小写 hash_name/mh/n →
      追踪池补量恒为 0（只有持仓那 32 件）。
    """
    if limit <= 0:
        return []
    out = []
    # eco_tracked.json: [{HashName, GoodsName, ...}, ...]
    p = os.path.join(REPO, 'eco_tracked.json')
    if os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f:
                arr = json.load(f)
            if isinstance(arr, list):
                for x in arr:
                    if len(out) >= limit:
                        break
                    if isinstance(x, str):
                        out.append(x)
                    elif isinstance(x, dict):
                        for k in ('HashName', 'hash_name', 'mh', 'market_hash', 'name', 'n'):
                            v = x.get(k)
                            if v:
                                out.append(v)
                                break
        except Exception as e:
            print('提示：读 eco_tracked.json 失败（%s）' % e)
    # market.json: dict，items 是 list
    if len(out) < limit:
        p2 = os.path.join(REPO, 'market.json')
        if os.path.exists(p2):
            try:
                with open(p2, encoding='utf-8') as f:
                    d = json.load(f)
                for x in (d.get('items') or []):
                    if len(out) >= limit:
                        break
                    if isinstance(x, dict):
                        for k in ('hash_name', 'mh', 'market_hash', 'name_en', 'name', 'n'):
                            v = x.get(k)
                            if v:
                                out.append(v)
                                break
            except Exception:
                pass
    return out[:limit]


def fetch_one(hn, typ, key, retries=2):
    """拉单件单档 K 线，返回 bars 列表 [{d,o,h,l,c,n}]，失败返回 None。"""
    payload = {'marketHashName': hn, 'type': typ, 'platform': PLATFORM}
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode('utf-8'),
        headers={'Authorization': 'Bearer %s' % key,
                 'Content-Type': 'application/json',
                 'User-Agent': 'Apifox/1.0.0'})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                d = json.loads(resp.read())
            break
        except Exception as e:
            if attempt >= retries:
                return None
            # 限频要退避；网络抖动重试即可
            time.sleep(3.0 if '429' in str(e) or '4005' in str(e) else 1.0)
    else:
        return None
    if not d.get('success'):
        return None
    data = d.get('data') or []
    arr = list(data.values()) if isinstance(data, dict) else data
    bars = []
    for row in arr:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        try:
            ts = int(float(row[0]))
            o, c, h, l = float(row[1]), float(row[2]), float(row[3]), float(row[4])
        except (TypeError, ValueError):
            continue
        if h < max(o, c) or l > min(o, c):
            # 不变量被破坏 = 字段顺序理解错了。宁可丢掉这根，也不要画错影线。
            continue
        bars.append({
            'd': time.strftime('%Y-%m-%dT%H:%M', time.localtime(ts)),
            'o': round(o, 2), 'h': round(h, 2),
            'l': round(l, 2), 'c': round(c, 2),
            # 官方数据**不提供采样点数**（它是成交口径，不存在「样本不足」）。
            # 用 n=0 + q=2 表示「官方成交口径，密度不适用」——
            # 前端 q=2 是「影线正常」，正好符合语义。
            'n': 0, 'r': 1, 'q': 2,
        })
    return bars or None


def file_signature(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return '%d:%s' % (os.path.getsize(path), h.hexdigest())


def push_out(path, meta):
    if os.environ.get('KRONOS_NO_PUSH'):
        print('KRONOS_NO_PUSH 已设置，跳过推送')
        return
    #⚠ 推送用的是 **GH_TOKEN**，不是 STEAMDT_KEY —— 两者互不相干。
    #   早先这里写成读 SteamDT key，于是「SteamDT 有key」被当成了「能推送」，
    #   而真正的 GH_TOKEN 缺失时会被下面 _gh_token() 返回 None → 推送静默失败。
    if not _gh_token():
        print('  ⚠ 没有 GH_TOKEN，%s 未推送（前端会读旧数据）' % os.path.basename(path))
        return
    rel = os.path.relpath(path, REPO).replace('\\', '/')
    sig = file_signature(path)
    sigf = os.path.join(REPO, '.kline_pushed', os.path.basename(path) + '.sig')
    try:
        os.makedirs(os.path.dirname(sigf), exist_ok=True)
        with open(sigf, encoding='utf-8') as f:
            if f.read().strip() == sig:
                print('  内容与上次推送一致，跳过 %s' % rel)
                return
    except Exception:
        pass
    try:
        sys.path.insert(0, REPO)
        from github_api_push import api_push_all, _ssl_ctx
        ok, failed = api_push_all(
            files=[rel],
            message=('chore(kline): 刷新 SteamDT官方 %s %s（%d 件 / %d 根）'
                     % (meta['label'], time.strftime('%Y-%m-%d %H:%M'),
                        meta['n'], meta['bars_total'])),
            repo=os.environ.get('KRONOS_REPO') or 'hintime/cs2-dashboard',
            token=_gh_token(),
            ctx=_ssl_ctx(), base_dir=REPO)
        if ok:
            try:
                with open(sigf, 'w', encoding='utf-8') as f:
                    f.write(sig)
            except Exception:
                pass
            print('  已推送 %s' % rel)
        else:
            print('  ⚠ 推送失败: %s' % failed)
    except Exception as e:
        print('  ⚠ 推送异常（不影响已生成的文件）: %s' % e)


def _gh_token():
    """读 GH_TOKEN（用于推送）。⚠ 不能拿 STEAMDT_KEY 推 GitHub —— 两者不是一回事，
    混用会拿「推送成功」掩盖「token 无仓库权限」这种问题。"""
    t = os.environ.get('GH_TOKEN', '')
    if t:
        return t
    try:
        with open(os.path.join(REPO, 'local_keys.env'), encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('export '):
                    line = line[len('export '):].strip()
                if line.startswith('GH_TOKEN'):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return None


NOTE = {
    '1h': 'SteamDT 官方 1 小时K（type=1），每根对应一个整点，'
          '高低收为该小时内真实成交区间；BUFF 平台口径；仅保留最近约 8 天（200 根）',
    '1d': 'SteamDT 官方日 K（type=2），BUFF 平台口径；'
          '官方可回溯 365 天，此处保留最近 240 天（约 8 个月），更远请切周K',
    '1w': 'SteamDT 官方周 K（type=3），BUFF 平台口径；全量约 4.3 年（回溯到 2022 年）',
}
CAVEAT = {
    '1h': '官方成交口径，高低为该时段真实成交极值（非采样近似）；'
          '平台为 BUFF，与站内 eco/buff 主源略有价差',
    '1d': '官方成交口径。⚠ 同一天 BUFF 与 Steam/悠悠 的价差可达 30%，'
          '看趋势可信、比绝对价位请以站内行情为准',
    '1w': '官方成交口径，周内聚合。跨度 4.3 年（回溯到 2022 年）',
}


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit-items', type=int, default=300,
                    help='追踪池补量上限；持仓永远全量。0 = 只拉持仓')
    ap.add_argument('--only', choices=list(GRANS), help='只拉某一档')
    ap.add_argument('--no-push', action='store_true')
    ap.add_argument('--throttle', type=float, default=THROTTLE)
    return ap.parse_args()


def main():
    args = parse_args()
    key = read_key()
    if not key or key == 'test_key':
        print('⚠ 未配置 STEAMDT_KEY，跳过（文件保持上次版本）')
        return
    hold = load_holdings_keys()
    extra = load_track_keys(args.limit_items)
    # 持仓优先，且去重
    names, seen = [], set()
    for hn in hold + extra:
        if hn and hn not in seen:
            seen.add(hn)
            names.append(hn)
    print('拉取目标：持仓 %d 件 + 追踪池 %d 件 = 去重后 %d 件'
          % (len(hold), len(extra), len(names)))
    print('预计请求 %d 次（限频 120/分钟，节流 %.1fs 约需 %.0f 秒）'
          % (len(names) * (1 if args.only else 3), args.throttle,
             len(names) * (1 if args.only else 3) * args.throttle))

    grans = [args.only] if args.only else ['1h', '1d', '1w']
    for g in grans:
        cfg = GRANS[g]
        t0 = time.time()
        out_items, nfail, nbars = [], 0, 0
        for i, hn in enumerate(names):
            bars = fetch_one(hn, cfg['type'], key)
            time.sleep(args.throttle)
            if not bars:
                nfail += 1
                continue
            bars = bars[-MAX_BARS[g]:]
            # ⚠ items 必须是 **list**（不是 dict）。前端 loadKline 里是
            #   `for (i=0; i<d.items.length; i++)` —— 若这里传 dict，
            #   d.items.length 是 undefined、循环一次都不执行 → 前端拿到空 map
            #   → 表现为「官方数据明明生成了但页面没数据」，且不报任何错。
            #   （2026-10-07 实测踩过：本地校验脚本报 items is not iterable
            #     才暴露出来。）
            out_items.append({'hash_name': hn, 'bars': bars})
            nbars += len(bars)
            if (i + 1) % 50 == 0:
                print('  [%s] %d/%d  %.0fs' % (g, i + 1, len(names), time.time() - t0),
                      flush=True)
        if not out_items:
            print('  [%s] 无数据，跳过（保留上次文件）' % g)
            continue
        all_d = [b['d'] for it in out_items for b in it['bars']]
        meta = {
            'granularity': g,
            'label': cfg['label'],
            'file': cfg['file'],
            'source': 'SteamDT 官方 open.steamdt.com/open/cs2/item/v1/kline',
            'platform': PLATFORM,
            'date': time.strftime('%Y-%m-%d %H:%M'),
            'n': len(out_items),
            'n_failed': nfail,
            'bars_total': nbars,
            'span': '%s ~ %s' % (min(all_d), max(all_d)),
            'source_note': NOTE[g],
            'caveat': CAVEAT[g],
            'items': out_items,
        }
        out = os.path.join(REPO, cfg['file'])
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, separators=(',', ':'))
        print('  写出 %s  %d 件（失败 %d）/ %d 根 / %s / %.2f MB  %.0fs'
              % (cfg['file'], len(out_items), nfail, nbars, meta['span'],
                 os.path.getsize(out) / 1048576.0, time.time() - t0))
        if not args.no_push:
            push_out(out, meta)


if __name__ == '__main__':
    main()