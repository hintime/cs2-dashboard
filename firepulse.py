#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FirePulse \u6570\u636e\u6e90\u5c01\u88c5

API: https://open.firepulse.com.cn/open
- \u9274\u6743: header  Api-Key
- \u9650\u989d: 5000 \u6b21/\u5929, 1 \u6b21/\u79d2\uff08\u672c\u6a21\u5757\u5185\u7f6e\u8282\u6d41\uff09
- \u4ec5\u672c\u673a runner \u53ef\u7528\uff08\u9700 IP \u767d\u540d\u5355\uff09

\u5bf9\u5916\u63a5\u53e3\uff1a
  fetch_overview()                \u5927\u76d8\uff08\u9970\u54c1\u6307\u6570/\u6210\u4ea4\u989d/\u6da8\u8dcc\u5206\u5e03/\u8d2a\u5a6a\u6307\u6570\uff09
  search_skin(keyword)            \u9970\u54c1ID\u67e5\u8be2
  fetch_detail(skin_id)           \u5355\u4ef6\u8be6\u60c5\uff0810 \u4e2a\u5e73\u53f0\u4ef7\u683c\uff09
  fetch_overview_for_prompt()     \u4f9b AI Prompt \u7528\u7684\u4e00\u53e5\u8bdd\u5927\u76d8\u6458\u8981
"""
import os
import sys
import json
import time
import urllib.request
import urllib.error

BASE = 'https://open.firepulse.com.cn/open'
KEY = os.environ.get('FIREPULSE_KEY', '')

# \u8282\u6d41\uff1a\u5b98\u65b9\u6700\u5c0f\u95f4\u9694 1 \u79d2
_MIN_INTERVAL = 1.05
_last_call = [0.0]
_stats = {'calls': 0, 'errors': 0, 'limited': 0}


def enabled():
    return bool(KEY)


def stats():
    return dict(_stats)


def _throttle():
    gap = time.time() - _last_call[0]
    if gap < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - gap)
    _last_call[0] = time.time()


def _post(path, body=None, timeout=25, retry=2):
    """POST \u8c03\u7528\uff1a\u81ea\u52a8\u8282\u6d41 + 429 \u91cd\u8bd5\uff0c\u5931\u8d25\u8fd4\u56de None\uff08\u8c03\u7528\u65b9\u81ea\u884c\u964d\u7ea7\uff09"""
    if not KEY:
        return None
    url = BASE + path
    for attempt in range(retry + 1):
        _throttle()
        req = urllib.request.Request(
            url, data=json.dumps(body or {}).encode('utf-8'),
            headers={'Api-Key': KEY, 'Content-Type': 'application/json',
                     'User-Agent': 'cs2-dashboard/1.0'}, method='POST')
        try:
            _stats['calls'] += 1
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8', 'replace'))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                _stats['limited'] += 1
                wait = 1.5 * (attempt + 1)
                print('[FirePulse] 429 \u9650\u6d41\uff0c\u7b49\u5f85 %.1fs' % wait, file=sys.stderr)
                time.sleep(wait)
                continue
            _stats['errors'] += 1
            print('[FirePulse] HTTP %s %s: %s' % (e.code, path, e.read()[:150]), file=sys.stderr)
            return None
        except Exception as e:
            _stats['errors'] += 1
            print('[FirePulse] %s \u8c03\u7528\u5931\u8d25: %s' % (path, str(e)[:120]), file=sys.stderr)
            return None
    return None


# ─────────────────────── \u5927\u76d8 ───────────────────────
def fetch_overview():
    """\u9996\u9875\u5927\u76d8\uff1a\u9970\u54c1\u6307\u6570+\u6210\u4ea4\u91cf\u989d+\u6da8\u8dcc\u5206\u5e03+\u8d2a\u5a6a\u6307\u6570"""
    d = _post('/v1/homepage/large_cap')
    if not d or d.get('code') not in (0, 200):
        return None
    data = d.get('data') or {}
    ib = data.get('index_basic_info') or {}
    tb = data.get('trade_basic_info') or {}
    ud = data.get('updown_basic_info') or {}
    gd = data.get('greedy_info') or {}
    out = {
        'index': {
            'name': ib.get('name', ''),
            'current': ib.get('current_index'),
            'change': ib.get('change_index'),
            'change_pct': ib.get('change_index_percent'),
            'max': ib.get('max_index'),
            'min': ib.get('min_index'),
            'change_days': ib.get('change_day'),
            'latest_time': ib.get('latest_time'),
        },
        'trade': {
            'today_amount': tb.get('today_amount'),
            'yesterday_amount': tb.get('previous_amount'),
            'today_volume': tb.get('today_volume'),
            'yesterday_volume': tb.get('previous_volume'),
            'amount_mom': tb.get('mom_trade_amount'),
            'volume_mom': tb.get('mom_trade_volume'),
        },
        'updown': {
            'up': ud.get('up_count'),
            'flat': ud.get('flat_count'),
            'down': ud.get('down_count'),
        },
        'greedy': {
            'value': gd.get('greedy'),
            'label': gd.get('greedy_status_label'),
            'change': gd.get('greedy_change'),
        },
        'trend_24h': (data.get('index_value') or [])[:48],
        'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'source': 'firepulse',
    }
    return out


def fetch_overview_for_prompt():
    """\u4f9b AI Prompt \u7528\u7684\u4e00\u53e5\u8bdd\u5927\u76d8\u6458\u8981\uff1b\u5931\u8d25\u8fd4\u56de\u7a7a\u5b57\u7b26\u4e32"""
    o = fetch_overview()
    if not o:
        return ''
    i = o['index']
    g = o['greedy']
    try:
        return ('\u9970\u54c1\u6307\u6570 %.2f (%.2f%%)%s\uff0c24h \u6210\u4ea4\u989d %.0f\u4e07\uff08\u73af\u6bd4 %.1f%%\uff09\uff0c'
                '\u6da8%d/\u8dcc%d\uff0c\u8d2a\u5a6a\u6307\u6570 %.1f(%s)') % (
            i['current'] or 0, i['change_pct'] or 0,
            ('\u8fde%s%d\u5929' % ('\u6da8' if (i['change_days'] or 0) > 0 else '\u8dcc', abs(i['change_days'] or 0))) if i.get('change_days') else '',
            (o['trade']['today_amount'] or 0) / 10000, o['trade']['amount_mom'] or 0,
            o['updown']['up'] or 0, o['updown']['down'] or 0,
            g['value'] or 0, g['label'] or '')
    except Exception:
        return ''


# ─────────────────────── \u9970\u54c1 ───────────────────────
def search_skin(keyword, limit=20):
    """\u6309\u540d\u79f0\u641c\u7d22\u9970\u54c1\uff0c\u8fd4\u56de [{id,name,market_hash_name,price,...}]"""
    d = _post('/v1/wiki/skin_search', {'name': keyword})
    if not d or d.get('code') not in (0, 200):
        return []
    lst = (d.get('data') or {}).get('list') or []
    return lst[:limit]


def fetch_detail(skin_id):
    """\u5355\u4ef6\u8be6\u60c5\uff1a10 \u4e2a\u5e73\u53f0\u7684\u5728\u552e/\u6c42\u8d2d\u4ef7\u4e0e\u6570\u91cf + \u5b58\u4e16\u91cf + \u6da8\u8dcc\u5e45

    \u6ce8\u610f\uff1aAPI \u8981\u6c42 id \u4e3a\u6574\u578b\uff0c\u800c\u641c\u7d22\u63a5\u53e3\u8fd4\u56de\u7684\u662f\u5b57\u7b26\u4e32\uff08\u8d85\u8fc7 JS \u5b89\u5168\u6574\u6570\uff09\u3002
    """
    try:
        sid = int(skin_id)
    except Exception:
        return None
    d = _post('/v1/quote/detail', {'id': sid})
    if not d or d.get('code') not in (0, 200):
        return None
    return d.get('data') or None


def pick_platform(platforms, names):
    """\u4ece platforms \u6570\u7ec4\u91cc\u53d6\u6307\u5b9a\u5e73\u53f0\uff08\u540d\u79f0\u5339\u914d\uff0c\u4e0d\u533a\u5206\u5927\u5c0f\u5199\uff09"""
    if not platforms:
        return None
    want = {n.lower() for n in names}
    for p in platforms:
        if str(p.get('name', '')).strip().lower() in want:
            return p
    return None


def to_dashboard_fields(detail):
    """\u628a FirePulse \u8be6\u60c5\u8f6c\u6210\u770b\u677f\u7edf\u4e00\u5b57\u6bb5\uff08\u4e0e BUFF/\u60a0\u60a0\u5b57\u6bb5\u540d\u5bf9\u9f50\uff09"""
    if not detail:
        return {}
    plats = detail.get('platforms') or []
    buff = pick_platform(plats, ['BUFF']) or {}
    yyyp = pick_platform(plats, ['悠悠有品', 'UUYP', 'YOUPIN']) or {}
    igxe = pick_platform(plats, ['IGXE']) or {}
    eco = pick_platform(plats, ['ECOSteam', 'ECO']) or {}
    out = {
        'fp_current_price': detail.get('current_price'),
        'fp_today_ratio': detail.get('today_ratio'),
        'fp_week_ratio': detail.get('week_ratio'),
        'fp_month_ratio': detail.get('month_ratio'),
        'fp_total_supply': detail.get('total_supply'),
        'fp_rarity': detail.get('rarity'),
        'fp_updated_at': detail.get('updated_at'),
        'fp_platform_count': len(plats),
    }
    if buff:
        out['buff_sell'] = buff.get('sell_price') or 0
        out['buff_sell_num'] = buff.get('sell_count') or 0
        out['buff_buy'] = buff.get('buy_price') or 0
        out['buff_buy_num'] = buff.get('buy_count') or 0
        out['buff_source'] = 'BUFF'
    if yyyp:
        out['yyyp_sell'] = yyyp.get('sell_price') or 0
        out['yyyp_sell_num'] = yyyp.get('sell_count') or 0
        out['yyyp_buy'] = yyyp.get('buy_price') or 0
        out['yyyp_buy_num'] = yyyp.get('buy_count') or 0
    if igxe:
        out['igxe_sell'] = igxe.get('sell_price') or 0
        out['igxe_sell_num'] = igxe.get('sell_count') or 0
    if eco:
        out['eco_platform_price'] = eco.get('sell_price') or 0
    return out


def fetch_price_rank(rank_type=1, date_range=7, limit=50, sort='desc', extra_filter=None):
    """\u4ef7\u683c\u699c\u5355\u3002rank_type: 1\u6da8\u5e45 2\u8dcc\u5e45 3\u6da8\u5e45\u7387 4\u8dcc\u5e45\u7387

    \u26a0\ufe0f \u5b9e\u6d4b\u7ed3\u8bba\uff1a\u539f\u59cb\u699c\u5355\u524d\u5217\u5e38\u4e3a\u6781\u7aef\u566a\u58f0\uff08\u5370\u82b1/\u7eaa\u5ff5\u54c1/StatTrak\uff0c\u5b58\u4e16\u91cf\u4e3a 0\uff09\uff0c
    \u4e0d\u5b9c\u76f4\u63a5\u7528\u4f5c\u63a8\u8350\u5019\u9009\uff0c\u9700\u914d\u5408 quality_filter() \u4f7f\u7528\u3002
    """
    body = {'type': rank_type, 'date_range': date_range, 'limit': limit, 'sort': sort}
    if extra_filter:
        body['filter'] = extra_filter
    d = _post('/v1/stats/price_rank', body)
    if not d or d.get('code') not in (0, 200):
        return []
    return d.get('data') or []


# \u8d28\u91cf\u8fc7\u6ee4\uff1a\u6392\u9664\u9879\u76ee\u5df2\u5b9a\u7684\u6392\u9664\u7c7b\u522b + \u566a\u58f0\u884c\u60c5
_EXCLUDE_PREFIX = ('StatTrak\u2122', 'StatTrak', 'Souvenir', '\u7eaa\u5ff5\u54c1', '\u5370\u82b1', 'Sticker')
_EXCLUDE_WEAR = {'\u7834\u635f\u4e0d\u582a', '\u6218\u75d5\u7d2f\u7d2f'}


def quality_filter(items, min_price=1.0, max_abs_ratio=100.0, require_supply=False):
    """\u8fc7\u6ee4\u6389\u66b4\u6da8\u66b4\u8dcc\u3001\u65e0\u5b58\u4e16\u91cf\u3001\u6392\u9664\u7c7b\u522b\u7684\u566a\u58f0\u6761\u76ee"""
    out = []
    for it in items or []:
        name = str(it.get('name', ''))
        if any(name.startswith(p) or ('（%s）' % p) in name or p in name for p in _EXCLUDE_PREFIX):
            continue
        if any(w in name for w in _EXCLUDE_WEAR):
            continue
        try:
            price = float(it.get('price') or 0)
        except Exception:
            continue
        if price < min_price:
            continue
        try:
            ratio = abs(float(it.get('ratio') or 0))
        except Exception:
            ratio = 999
        if ratio > max_abs_ratio:
            continue
        if require_supply and not (it.get('total_supply') or 0):
            continue
        out.append(it)
    return out


# ─────────────────────── 板块 ───────────────────────
def fetch_sectors(category_type=0):
    """板块列表。category_type: 0全部 -1热门 2一级"""
    d = _post('/v1/category/list/new', {'category_type': category_type})
    if not d or d.get('code') not in (0, 200):
        return []
    return d.get('data') or []


def fetch_sector_kline(category_id, date_type=1, date_range=1):
    """板块K线。date_type: 1时线 2日线 3周线；date_range: 月数(≤12)

    返回 [[ts, 开, 收, 低, 高, 成交额, 成交量], ...]
    """
    try:
        cid = int(category_id)
    except Exception:
        return []
    d = _post('/v1/category/k/data',
              {'category_id': cid, 'date_type': date_type, 'date_range': date_range})
    if not d or d.get('code') not in (0, 200):
        return []
    return d.get('data') or []


def fetch_sector_overview(top_n=10, kline_for_top=8):
    """板块概况：列表 + 对热门板块取 K线算涨跌幅

    用量：1 (列表) + kline_for_top（每个板块1次）。
    """
    arr = fetch_sectors(0)
    if not arr:
        return None
    out = []
    for it in arr:
        out.append({'id': it.get('id'), 'name': it.get('name'),
                    'current_index': it.get('current_index'), 'img': it.get('img')})
    # 对排名靠前的板块取 K线，算出涨跌幅（用最后两个点）
    enriched = 0
    for item in out[:kline_for_top]:
        k = fetch_sector_kline(item['id'], date_type=2, date_range=1)   # 日线，更稳
        if len(k) >= 2:
            try:
                prev = float(k[-2][2])
                cur = float(k[-1][2])
                if prev:
                    item['ratio'] = round((cur - prev) / prev * 100, 2)
            except Exception:
                pass
        if 'ratio' not in item:
            k2 = fetch_sector_kline(item['id'], date_type=1, date_range=1)
            if len(k2) >= 2:
                try:
                    prev = float(k2[-2][2])
                    cur = float(k2[-1][2])
                    if prev:
                        item['ratio'] = round((cur - prev) / prev * 100, 2)
                except Exception:
                    pass
        if 'ratio' in item:
            enriched += 1
    ranked = sorted([x for x in out if 'ratio' in x], key=lambda x: -x['ratio'])
    return {
        'list': out,
        'ranked': ranked,
        'up': [x for x in ranked if x['ratio'] > 0][:top_n],
        'down': [x for x in ranked if x['ratio'] < 0][-top_n:],
        'enriched': enriched,
        'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'source': 'firepulse',
    }


# ─────────────────────── 大盘时序（累积）───────────────────────
OVERVIEW_HIST = 'market_overview_history.json'


def append_overview_history(ov, path):
    """把当前大盘快照追加进历史（按小时去重，保留最近 720 条）

    返回 (历史数据, 是否新增)
    """
    if not ov:
        return None, False
    hist = []
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                hist = json.load(f)
            if not isinstance(hist, list):
                hist = []
        except Exception:
            hist = []
    hour_key = time.strftime('%Y-%m-%dT%H:00')
    rec = {
        't': hour_key,
        'idx': (ov.get('index') or {}).get('current'),
        'chg': (ov.get('index') or {}).get('change_pct'),
        'amount': (ov.get('trade') or {}).get('today_amount'),
        'volume': (ov.get('trade') or {}).get('today_volume'),
        'up': (ov.get('updown') or {}).get('up'),
        'down': (ov.get('updown') or {}).get('down'),
        'greedy': (ov.get('greedy') or {}).get('value'),
    }
    if hist and hist[-1].get('t') == hour_key:
        hist[-1] = rec          # 同一小时内覆盖
        added = False
    else:
        hist.append(rec)
        added = True
    hist = hist[-720:]
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(hist, f, ensure_ascii=False, separators=(',', ':'))
    except Exception as e:
        print('[FirePulse] 写入大盘历史失败: %s' % e, file=sys.stderr)
        return hist, False
    return hist, added


# ─────────────────────── 持仓精确化 ───────────────────────
def enrich_items(items, id_cache=None, max_items=30, on_progress=None):
    """对指定饰品列表补充 FirePulse 多平台价格字段

    items: [{'名称或 market_hash', ...}]  会就地 update
    id_cache: {name: skin_id} 缓存（避免重复 search）
    用量：每项最多 2 次（search + detail），命中缓存时 1 次
    返回：成功补充的数量
    """
    if not enabled() or not items:
        return 0
    if id_cache is None:
        id_cache = {}
    ok = 0
    for it in items[:max_items]:
        name = it.get('market_hash') or it.get('name') or it.get('n') or ''
        if not name:
            continue
        sid = id_cache.get(name)
        if not sid:
            lst = search_skin(name, limit=1)
            if lst:
                sid = lst[0].get('id')
                if sid:
                    id_cache[name] = sid
        if not sid:
            continue
        det = fetch_detail(sid)
        f = to_dashboard_fields(det)
        if f:
            it.update(f)
            ok += 1
        if on_progress:
            on_progress(name, ok)
    return ok
