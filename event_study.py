# -*- coding: utf-8 -*-
"""历史事件研究（event study）：公告发布后 3/7/14 天，市场实际涨跌 vs 同期基准。

用途：给「AI 空投监控」的利好/利空判断提供**有数据支撑的先验**，把 AI 观点变成
「历史上 N 个公告日后 7 天，同批物品中位涨跌 +X%，同期基准 +Y%，超额 +Z%」的统计陈述。
被 update.py 的 all 轮调用（生成 event_study.json），供 generate_ai_news_impact 写入 prompt。

方法（2026-09-26 定稿）：
- 事件源：Steam 官方公告（Community Announcements），拉 100 条，与价格库覆盖期求交集；
  同日去重（例行 "Counter-Strike 2 Update" 让位给内容型标题）。
- 分类：major（内容型大更新）/ esports（赛事）/ routine（例行更新）/ other。
- 市场口径：**同批对比**——T-1 与 T+N 都出现的 buff 渠道物品（≥¥5），各自算涨跌幅取中位数。
  （避免不同日期覆盖物品构成不同造成的假信号；¥5 以下白给件价格长期不动会把中位钉在 0。）
- 同期基准：**非事件日**（且避开事件日 ±3 天）用同样 horizon 算中位涨跌取均值 → 超额 = 事件均值 − 基准均值。
- 数据质量：两日价格几乎全同 = 该期价格未真实更新（重复落库）→ 标 stale 并剔除。
  ⚠ 实测 7 月价格更新稀疏，大部分事件因此无效；9/20 起才为真实高频数据。

输出 event_study.json（字段与 update.py 集成代码约定一致）:
{generated, window, method, data_quality, note, n_events, n_valid_events,
 events:[{date,title,cat,base_day,d3,d7,d14,有效}],
 summary:{n_events, n_pool, ret_3d:{event_mean,baseline_mean,excess,n_base,n_events,up_pct,dn3_pct},
          ret_7d:{...}, ret_14d:{...}, verdict, by_cat:{...}}}
"""
import datetime as dt
import json
import os
import sqlite3
import time

DATA_DIR = os.environ.get('CS2_DATA_DIR') or os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get('PRICE_HIST_DB') or '/home/ubuntu/cs2-run/price_history.db'
OUT = os.path.join(DATA_DIR, 'event_study.json')
DB_START = '2026-06-28'      # buff 渠道历史起点（实测）
PRICE_FLOOR = 5.0            # 价格下限：剔除白给件（价格长期不动会把中位钉在 0）
STALE_RATIO = 0.01           # 变动物品占比 <1% 视为该期价格未真实更新

CAT_RULES = [
    ('esports', ['cologne', 'iem', 'major', 'finale', 'playoff', 'grand final', 'katowice', 'esl']),
    ('major', ['season', 'armory', 'case', 'capsule', 'operation', 'mode', 'map', 'cache', 'music kit',
               'sticker', 'rush', 'arsenal', 'collection', 'anime', 'premiere', 'rank']),
    ('routine', ['counter-strike 2 update', 'update', 'patch', 'fix']),
]


def fetch_announcements(count=100):
    """抓 Steam 官方公告（只留 Community Announcements）

    ⚠ 用 curl 而非 urllib：服务器 python urllib 访问 api.steampowered.com 会 SSL 握手超时
    （IPv6 优先），curl -4 实测 200/0.34s。
    ⚠ **不要带 feeds= 参数**（实测服务器上带该参数 40s 超时 http=000，不带 1.5s 200）——
    官方 feed 过滤在代码里做。
    ⚠ 该 API 在服务器侧时好时坏 → curl 重试 3 次；仍失败则回退本地缓存 news_history.json
    （公告列表变化很慢，缓存数小时完全可用），避免整体失败。
    """
    url = 'https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid=730&count=%d&maxlength=0&format=json' % count
    cache_path = os.path.join(DATA_DIR, 'news_history.json')

    def _parse(raw):
        items = json.loads(raw).get('appnews', {}).get('newsitems', [])
        out = []
        for it in items:
            feed = (it.get('feedlabel') or '') + '|' + (it.get('feedname') or '')
            if 'Community Announcements' not in feed and 'steam_community_announcements' not in (it.get('url') or ''):
                continue
            out.append({'date': time.strftime('%Y-%m-%d', time.gmtime(it['date'])),
                        'title': (it.get('title') or '').strip()})
        return out

    raw = None
    try:
        import subprocess
        for _try in range(3):
            r = subprocess.run(['curl', '-4', '-s', '--retry', '2', '--max-time', '25', url],
                               capture_output=True, text=True, timeout=90)
            if r.returncode == 0 and (r.stdout or '').strip().startswith('{'):
                raw = r.stdout
                break
            print('  [WARN] 公告抓取第 %d 次失败 (rc=%s)' % (_try + 1, r.returncode))
    except Exception as _e:
        print('  [WARN] curl 不可用: %s' % str(_e)[:80])

    if raw is not None:
        try:
            out = _parse(raw)
            if out:
                json.dump(out, open(cache_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                return out
        except Exception as _e:
            print('  [WARN] 公告解析失败: %s' % str(_e)[:80])

    if os.path.exists(cache_path):
        print('  [WARN] 使用缓存公告列表 news_history.json（线上抓取失败）')
        return json.load(open(cache_path, encoding='utf-8'))
    raise RuntimeError('公告抓取失败且无缓存')


def classify(title):
    t = (title or '').lower()
    for cat, kws in CAT_RULES:
        if any(k in t for k in kws):
            return cat
    return 'other'


def median(xs):
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    return round(s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0, 2)


def mean(xs):
    return round(sum(xs) / len(xs), 2) if xs else None


def load_prices(conn):
    """一次读入所有日的 buff 渠道价（缓存，避免逐日重复全表扫描）"""
    days = [r[0] for r in conn.execute(
        "SELECT DISTINCT substr(ts,1,10) d FROM prices WHERE channel='buff' AND ts >= ? ORDER BY d",
        (DB_START,)).fetchall()]
    cache = {}
    for d in days:
        rows = conn.execute(
            "SELECT item_name, AVG(price) FROM prices WHERE channel='buff' AND substr(ts,1,10)=? "
            "GROUP BY item_name HAVING AVG(price) >= ?", (d, PRICE_FLOOR)).fetchall()
        cache[d] = {r[0]: float(r[1]) for r in rows}
    return days, cache


def compare(cache, base_day, later_day):
    """同批对比：两日都出现的物品涨跌分布；stale=价格几乎未更新"""
    if not base_day or not later_day or base_day == later_day:
        return {'day': later_day, 'n': 0, 'med': None, 'up': None, 'dn3': None, 'stale': None}
    b, l = cache.get(base_day) or {}, cache.get(later_day) or {}
    common = set(b) & set(l)
    chgs = [(l[i] / b[i] - 1) * 100 for i in common if b[i] > 0]
    if not chgs:
        return {'day': later_day, 'n': 0, 'med': None, 'up': None, 'dn3': None, 'stale': None}
    moved = sum(1 for x in chgs if abs(x) > 1e-9)
    return {'day': later_day, 'n': len(chgs), 'med': median(chgs),
            'up': round(sum(1 for x in chgs if x > 0) / len(chgs) * 100, 1),
            'dn3': round(sum(1 for x in chgs if x < -3) / len(chgs) * 100, 1),
            'stale': (moved / len(chgs)) < STALE_RATIO}


def shift(days_set, day, horizon, prefer='after', tol=3):
    t = dt.date.fromisoformat(day) + dt.timedelta(days=horizon)
    cands = []
    for d in days_set:
        gap = (dt.date.fromisoformat(d) - t).days
        if prefer == 'before' and gap > 0:
            continue
        if prefer == 'after' and gap < 0:
            continue
        if abs(gap) <= tol:
            cands.append((abs(gap), d))
    return sorted(cands)[0][1] if cands else None


def main():
    try:
        anns = fetch_announcements(100)
    except Exception as e:
        print('[EVENT] 公告获取失败，保留旧产物不覆盖: %s' % str(e)[:120])
        return
    by_day = {}
    for a in anns:
        if a['date'] < DB_START:
            continue
        cat = classify(a['title'])
        cur = by_day.get(a['date'])
        if cur is None or (cur['cat'] == 'routine' and cat != 'routine'):
            by_day[a['date']] = dict(a, cat=cat)
    evs = sorted(by_day.values(), key=lambda x: x['date'])

    conn = sqlite3.connect('file:%s?mode=ro' % DB, uri=True)
    days, cache = load_prices(conn)
    conn.close()
    days_set = set(days)
    print('公告事件 %d 个 | 库覆盖 %s 起共 %d 个数据日' % (len(evs), DB_START, len(days)))

    events = []
    for ev in evs:
        base = shift(days_set, ev['date'], -1, prefer='before')
        if not base:
            print('  跳过（无基准日）%s' % ev['date'])
            continue
        row = {'date': ev['date'], 'title': ev['title'][:60], 'cat': ev['cat'], 'base_day': base}
        for h in (3, 7, 14):
            ld = shift(days_set, ev['date'], h, prefer='after')
            row['d%d' % h] = compare(cache, base, ld)
        d7 = row['d7']
        row['有效'] = bool((d7.get('n') or 0) > 0 and not d7.get('stale'))
        events.append(row)
        print('  %s [%-9s] %-34s n=%-5s 7d中位=%-7s 上涨%%=%-5s 有效=%s' % (
            ev['date'], ev['cat'], ev['title'][:32], d7['n'], d7['med'], d7.get('up'), row['有效']))

    valid = [e for e in events if e['有效']]
    ev_days = set(e['date'] for e in events)

    def baseline_for(h):
        """同期基准：非事件日（避开事件日 ±3 天）用同样 horizon 的中位涨跌均值"""
        vals = []
        for d in days:
            dd = dt.date.fromisoformat(d)
            if any(abs((dd - dt.date.fromisoformat(ed)).days) <= 3 for ed in ev_days):
                continue
            ld = shift(days_set, d, h, prefer='after')
            if not ld:
                continue
            r = compare(cache, d, ld)
            if r['med'] is not None and not r['stale']:
                vals.append(r['med'])
        return mean(vals), len(vals)

    def pack(h):
        ekey = 'd%d' % h          # 事件明细里的字段名（d3/d7/d14）
        ev_vals = [e[ekey]['med'] for e in valid if (e.get(ekey) or {}).get('med') is not None]
        up = [e[ekey]['up'] for e in valid if (e.get(ekey) or {}).get('up') is not None]
        dn3 = [e[ekey]['dn3'] for e in valid if (e.get(ekey) or {}).get('dn3') is not None]
        b_mean, b_n = baseline_for(h)
        e_mean = mean(ev_vals)
        return {
            'event_mean': e_mean,
            'baseline_mean': b_mean,
            'excess': (round(e_mean - b_mean, 2) if (e_mean is not None and b_mean is not None) else None),
            'n_base': b_n,
            'n_events': len(ev_vals),
            'up_pct': mean(up), 'dn3_pct': mean(dn3),
        }

    pool_sizes = [e['d7']['n'] for e in valid if e['d7'].get('n')]
    n_valid = len(valid)
    summary = {
        'n_events': n_valid,
        'n_pool': median(pool_sizes) or 0,
        'ret_3d': pack(3), 'ret_7d': pack(7), 'ret_14d': pack(14),
    }

    r7 = summary['ret_7d']
    if n_valid >= 5 and r7['event_mean'] is not None and r7['baseline_mean'] is not None:
        _ex = r7['excess']
        _strength = '中等' if (abs(_ex) >= 1.0 and n_valid >= 8) else '偏弱'
        summary['verdict'] = (
            '历史上 %d 个有效公告事件后 7 天，同批物品中位涨跌 %+.2f%%，同期基准 %+.2f%%，'
            '超额 %+.2f%%（上涨物品占比 %.1f%%）→ 历史方向性支撑：%s'
            % (n_valid, r7['event_mean'], r7['baseline_mean'], _ex, r7['up_pct'] or 0, _strength))
    else:
        summary['verdict'] = (
            '有效样本仅 %d 个（价格库自 %s 起，7 月价格更新稀疏已剔除），统计意义很弱，'
            '只能作为很弱的先验；随 9 月起真实高频数据积累会自动增强。' % (n_valid, DB_START))

    def cat_pack(cat):
        sub = [e for e in valid if e['cat'] == cat]
        if not sub:
            return {'n': 0}
        return {'n': len(sub),
                'med7': median([e['d7']['med'] for e in sub if e['d7']['med'] is not None]),
                'up7': mean([e['d7']['up'] for e in sub if e['d7'].get('up') is not None])}
    summary['by_cat'] = {c: cat_pack(c) for c in ('major', 'esports', 'routine', 'other')}
    _content = [e for e in valid if e['cat'] in ('major', 'esports')]
    summary['by_cat']['content'] = {
        'n': len(_content),
        'med7': median([e['d7']['med'] for e in _content if e['d7']['med'] is not None]),
        'up7': mean([e['d7']['up'] for e in _content if e['d7'].get('up') is not None])}

    out = {
        'generated': time.strftime('%Y-%m-%d %H:%M'),
        'window': {'from': DB_START, 'to': time.strftime('%Y-%m-%d')},
        'method': '同批对比：T-1 与 T+N 都出现的 buff 渠道物品（≥¥5）算涨跌中位数；同窗口中位 vs 非事件期同期基准；T±3 天容差',
        'data_quality': ('⚠ 7 月价格更新稀疏，部分日期为重复落库（两日价格几乎全同）→ 该事件 有效=false 剔除；'
                         '9/20 起才是真实高频数据，当前有效样本少，结论仅供弱先验'),
        'note': '样本量=有效事件数（每事件内还有数千物品的同批样本）；n<5 时统计意义很弱',
        'n_events': len(events),
        'n_valid_events': n_valid,
        'events': events,
        'summary': summary,
    }
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print('\n已写出 %s' % OUT)
    print('汇总:', json.dumps(summary, ensure_ascii=False)[:600])


if __name__ == '__main__':
    main()
