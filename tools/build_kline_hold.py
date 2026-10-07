# -*- coding: utf-8 -*-
"""生成 kline_hold_1d.json —— 只含「当前持仓」的日K 裁剪版。

为什么要有这个文件（2026-10-07，实测数据，不是推测）
--------------------------------------------------------
整包日K 的体积/速度实测：
    kline_sd_1d.json  6.83 MB   经 CF Worker 回源 raw.githubusercontent
                               实测 ~13.5~25 KB/s → 拉完 **504 秒**
    kline_1d.json     5.48 MB   实测 ~590 KB/s → 9 秒（但**不含容器**）

前端 loadKline('1d') 是 Promise.all 死等两个源，所以 KL.loaded['1d'] 在
8 分钟内一直是 false → 详情卡走势图 / 列表迷你走势图**一直停在空态**。
而这两处只是要「最近 30 个收盘价」—— 为它下 12MB 完全不可接受。

裁剪版：持仓件（约 47 件）× 最近 120 根 × 只留 d/c → 约 150~200 KB，秒开。
整包降级为后台兜底（前端 3 秒后 lazy 拉），K 线态（要 OHLC 画蜡烛）仍走整包。

用法
    python tools/build_kline_hold.py                 # 生成 + 推送
    python tools/build_kline_hold.py --no-push       # 只生成
    python tools/build_kline_hold.py --bars 60       # 每 件保留 60 根
"""
import argparse
import json
import os
import re
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = 'kline_hold_1d.json'

# 源按优先级：官方（覆盖容器）→ 自采（覆盖部分官方没有的武器）
SOURCES = ['kline_sd_1d.json', 'kline_1d.json']


def load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print('  ⚠ 读取失败 %s: %s' % (os.path.basename(path), e))
        return None


def holdings_names():
    """持仓件的 market_hash 列表（去重、保序）。"""
    d = load_json(os.path.join(REPO, 'holdings.json'))
    if not d:
        print('  ⚠ 没有 holdings.json，无法裁剪')
        return []
    items = d.get('items') if isinstance(d, dict) else d
    if not isinstance(items, list):
        return []
    out, seen = [], set()
    for it in items:
        if not isinstance(it, dict):
            continue
        hn = it.get('market_hash') or it.get('name')
        if hn and hn not in seen:
            seen.add(hn)
            out.append(hn)
    return out


REPO_GH = os.environ.get('KRONOS_REPO') or 'hintime/cs2-dashboard'


def _gh_token():
    """读 GH_TOKEN：优先环境变量，其次 local_keys.env。

    ⚠ 为什么不复用 fetch_steamdt_kline.push_out：那个函数 import 的
      github_api_push 模块**只存在于服务器**，本地仓库里没有
      （实测本地跑报 No module named 'github_api_push'）——
      于是「本地生成成功但推送静默失败」，文件永远停在旧版。
      这里内联一份最小实现，本地/服务器都能推。"""
    t = os.environ.get('GH_TOKEN', '')
    if t:
        return t
    try:
        with open(os.path.join(REPO, 'local_keys.env'), encoding='utf-8') as f:
            for line in f:
                m = re.match(r'^\s*GH_TOKEN\s*=\s*(.+?)\s*$', line)
                if m:
                    return m.group(1).strip().strip('"\'')
    except Exception:
        pass
    return ''


def api_push(path, rel):
    """GitHub Contents API 单文件 PUT（绕开本机 git 443 不通的问题）。"""
    import base64
    import ssl
    import urllib.error
    import urllib.request
    tok = _gh_token()
    if not tok:
        return False, '没有 GH_TOKEN'
    try:
        ctx = ssl.create_default_context()
    except Exception:
        ctx = None
    with open(path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('ascii')
    body = {
        'message': 'chore(kline): 刷新持仓日K裁剪版 %s' % time.strftime('%Y-%m-%d %H:%M'),
        'content': b64, 'branch': 'main',
    }
    # 已存在则必须带 sha，否则 422
    try:
        req = urllib.request.Request(
            'https://api.github.com/repos/%s/contents/%s?ref=main' % (REPO_GH, rel),
            headers={'Authorization': 'token ' + tok, 'User-Agent': 'cs2-kline',
                     'Accept': 'application/vnd.github.v3+json'})
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            cur = json.loads(r.read().decode('utf-8'))
        body['sha'] = cur['sha']
    except Exception:
        pass
    try:
        req = urllib.request.Request(
            'https://api.github.com/repos/%s/contents/%s' % (REPO_GH, rel),
            data=json.dumps(body).encode('utf-8'), method='PUT',
            headers={'Authorization': 'token ' + tok, 'User-Agent': 'cs2-kline',
                     'Accept': 'application/vnd.github.v3+json',
                     'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
            json.loads(r.read().decode('utf-8'))
        return True, None
    except urllib.error.HTTPError as e:
        return False, 'HTTP %s %s' % (e.code, (e.read() or b'')[:150])
    except Exception as e:
        return False, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bars', type=int, default=120, help='每件保留最近多少根（默认120）')
    ap.add_argument('--no-push', action='store_true')
    args = ap.parse_args()

    names = holdings_names()
    print('持仓 %d 件' % len(names))

    # 逐源建索引：hash_name -> bars（后加载的低优先级不覆盖高优先级）
    idx = {}
    src_stat = {}
    for sf in SOURCES:
        d = load_json(os.path.join(REPO, sf))
        if not d or not isinstance(d.get('items'), list):
            src_stat[sf] = '缺失'
            continue
        src_stat[sf] = '%d 件' % len(d['items'])
        for it in d['items']:
            hn = it.get('hash_name')
            if hn and hn not in idx and isinstance(it.get('bars'), list):
                idx[hn] = it['bars']
    for sf in SOURCES:
        print('  源 %-18s %s' % (sf, src_stat.get(sf)))

    out_items, hit_sd, hit_own, miss, nbar = [], 0, 0, [], 0
    sd_names = None
    # 判定命中来源（仅用于日志）
    d0 = load_json(os.path.join(REPO, SOURCES[0]))
    sd_names = set(x.get('hash_name') for x in (d0 or {}).get('items', [])) if d0 else set()

    for hn in names:
        bars = idx.get(hn)
        if not bars:
            miss.append(hn)
            continue
        tail = bars[-args.bars:]
        # ⚠ 只留 d/c：详情卡/迷你图只要收盘价，OHLC 会把体积放大一倍多。
        #   字段名必须与整包一致（d/c），前端 _pickK 才能直接复用。
        slim = []
        for b in tail:
            if not isinstance(b, dict):
                continue
            c = b.get('c')
            if c is None:
                continue
            slim.append({'d': b.get('d', ''), 'c': round(float(c), 2)})
        if len(slim) < 8:
            miss.append(hn)
            continue
        out_items.append({'hash_name': hn, 'bars': slim})
        nbar += len(slim)
        if hn in sd_names:
            hit_sd += 1
        else:
            hit_own += 1

    print('命中：官方 %d / 自采 %d / 未命中 %d' % (hit_sd, hit_own, len(miss)))
    if miss:
        print('  未命中（会走整包兜底）: %s' % ', '.join(miss[:10]))

    if not out_items:
        print('⚠ 一件都没命中，不写出（保留上次文件）')
        return

    span = ''
    try:
        all_d = [b['d'] for it in out_items for b in it['bars'] if b['d']]
        span = '%s ~ %s' % (min(all_d), max(all_d))
    except Exception:
        pass

    meta = {
        'granularity': '1d',
        'label': '日K(持仓裁剪)',
        'file': OUT_FILE,
        'source': '由 kline_sd_1d.json / kline_1d.json 裁剪（只留持仓件最近 %d 根收盘价）' % args.bars,
        'platform': 'BUFF(官方) + ECO(自采)',
        'date': time.strftime('%Y-%m-%d %H:%M'),
        'n': len(out_items),
        'n_missed': len(miss),
        'bars_total': nbar,
        'span': span,
        # ⚠ 供前端识别：这是精简版，**没有 o/h/l**，不能用来画蜡烛
        'slim': True,
        'items': out_items,
    }
    out = os.path.join(REPO, OUT_FILE)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, separators=(',', ':'))
    print('写出 %s  %d 件 / %d 根 / %s / %.2f MB'
          % (OUT_FILE, len(out_items), nbar, span, os.path.getsize(out) / 1048576.0))

    if args.no_push or os.environ.get('KRONOS_NO_PUSH'):
        print('（--no-push，跳过推送）')
        return
    # 推送两路，任一成功即可：
    #   ① 内联 Contents API（本地/服务器都能用，不依赖 github_api_push）；
    #   ② 失败再走项目统一的 push_out（服务器上有 github_api_push 模块）。
    # ⚠ 顺序不能反：push_out 内部自己吞异常、只打印「推送异常」，
    #   调用方捕获不到 —— 先调它就永远发现不了它其实失败了。
    ok, err = api_push(out, OUT_FILE)
    if ok:
        print('  ✓ 已推送 %s（内联通道）' % OUT_FILE)
        return
    try:
        sys.path.insert(0, REPO)
        sys.path.insert(0, os.path.join(REPO, 'tools'))
        from fetch_steamdt_kline import push_out
        push_out(out, meta)
        print('  ✓ 已推送 %s（项目通道）' % OUT_FILE)
    except Exception as e2:
        print('  ⚠ 推送失败：内联 %s；项目 %s' % (err, e2))


if __name__ == '__main__':
    main()
