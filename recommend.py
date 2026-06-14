#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CS2 饰品购买推荐引擎
综合 CSQAQ（趋势数据）+ ECOSteam（全量供需数据）生成推荐

推荐策略：
1. 🔥 强势追涨 — 7日涨幅>5% 且 1日仍涨，趋势向上
2. 💎 低估捡漏 — ECO综合价远高于最低售价，有估值修复空间
3. 📉 超跌反弹 — 7日跌幅>8% 但有求购盘承接
4. ⚡ 供不应求 — 求购/在售比高，卖盘稀缺
"""
import json, time, base64, urllib.request, urllib.error, ssl, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eco_sign import get_eco_key, sign_eco

PARTNER_ID = 'da740aa96cc14cc594371f95469c90ac'
CSQ_KEY = os.environ.get('CSQ_API_TOKEN', 'HXGPY1R7L5W7K7F3O4K1E2N8')

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# ═══════════════ HTTP ═══════════════
def http_post_raw(url, body, headers=None, timeout=15):
    data = json.dumps(body, ensure_ascii=False).encode('utf-8')
    hdrs = {'Content-Type': 'application/json'}
    if headers: hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method='POST')
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                raw = r.read()
                # 检查 HTTP 429
                if hasattr(r, 'status') and r.status == 429:
                    wait = min(2 ** attempt, 60)
                    print(f'  [HTTP] 429 rate limited, retry in {wait}s (attempt {attempt+1}/5)')
                    time.sleep(wait)
                    continue
                for enc in ('utf-8', 'gbk', 'latin-1'):
                    try: return json.loads(raw.decode(enc))
                    except: continue
                return {}
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = min(2 ** attempt, 60)
                print(f'  [HTTP] 429 rate limited, retry in {wait}s (attempt {attempt+1}/5)')
                time.sleep(wait)
                continue
            if attempt == 4: raise
            time.sleep(2)
        except Exception as e:
            if attempt == 4: raise
            time.sleep(2)

# ═══════════════ FETCH CSQAQ ═══════════════
def fetch_csqaq_alerts():
    all_alerts = []
    seen = set()
    for sort_key in ('price_up_1d', 'price_down_1d'):
        for page in range(1, 5):
            body = {
                'page_index': page, 'page_size': 50,
                'filter': {'type': ['sticker', 'normal'], 'sort': [sort_key]},
                'show_recently_price': True
            }
            try:
                d = http_post_raw('https://api.csqaq.com/api/v1/info/get_rank_list',
                    body, headers={'ApiToken': CSQ_KEY}, timeout=15)
                items = d.get('data', {})
                if isinstance(items, dict): items = items.get('data', [])
                if not items: break
                for item in items:
                    iid = item.get('id')
                    if iid in seen: continue
                    seen.add(iid)
                    all_alerts.append({
                        'id': iid,
                        'name': item.get('name', ''),
                        'exterior': item.get('exterior_localized_name', ''),
                        'rarity': item.get('rarity_localized_name', ''),
                        'price': float(item.get('buff_sell_price') or 0),
                        'rate_1': round(float(item.get('buff_price_chg') or item.get('sell_price_rate_1') or 0), 2),
                        'rate_7': round(float(item.get('sell_price_rate_7') or 0), 2),
                        'rate_30': round(float(item.get('sell_price_rate_30') or 0), 2),
                        'img': item.get('img', ''),
                        # Multi-platform supply/demand
                        'buff_sell': int(item.get('buff_sell_num') or 0),
                        'buff_buy': int(item.get('buff_buy_num') or 0),
                        'buff_buy_price': float(item.get('buff_buy_price') or 0),
                        'yyyp_sell': int(item.get('yyyp_sell_num') or 0),
                        'yyyp_buy': int(item.get('yyyp_buy_num') or 0),
                        'yyyp_price': float(item.get('yyyp_sell_price') or 0),
                        'steam_sell': int(item.get('steam_sell_num') or 0),
                        'steam_buy': int(item.get('steam_buy_num') or 0),
                        'steam_buy_price': float(item.get('steam_buy_price') or 0),
                    })
                if len(items) < 50: break
            except Exception as e:
                print(f'[WARN] CSQAQ {sort_key} p{page}: {e}', file=sys.stderr)
            time.sleep(0.5)
    return all_alerts

# ═══════════════ CSQAQ 全量多平台价格 ═══════════════
def fetch_csqaq_all_prices():
    """获取 CSQAQ 全量饰品多平台价格数据（一次请求，需企业权限）。
    Returns: {market_hash_name: {buff_sell, buff_buy, ..., yyyp_sell, steam_buy, ...}}
    """
    try:
        url = 'https://api.csqaq.com/api/v1/goods/get_all_goods_info'
        resp = http_post_raw(url, {}, headers={'ApiToken': CSQ_KEY}, timeout=60)
        if resp.get('code') == 200 and resp.get('data'):
            items = resp['data']
            result = {}
            for item in items:
                mhn = item.get('market_hash_name', '')
                if not mhn:
                    continue
                result[mhn] = {
                    'buff_sell': float(item.get('buff_sell_price', 0) or 0),
                    'buff_buy': float(item.get('buff_buy_price', 0) or 0),
                    'buff_sell_num': int(item.get('buff_sell_num', 0) or 0),
                    'buff_buy_num': int(item.get('buff_buy_num', 0) or 0),
                    'yyyp_sell': float(item.get('yyyp_sell_price', 0) or 0),
                    'yyyp_buy': float(item.get('yyyp_buy_price', 0) or 0),
                    'yyyp_sell_num': int(item.get('yyyp_sell_num', 0) or 0),
                    'yyyp_buy_num': int(item.get('yyyp_buy_num', 0) or 0),
                    'c5_sell': float(item.get('c5_sell_price', 0) or 0),
                    'c5_buy': float(item.get('c5_buy_price', 0) or 0),
                    'c5_sell_num': int(item.get('c5_sell_num', 0) or 0),
                    'c5_buy_num': int(item.get('c5_buy_num', 0) or 0),
                    'igxe_sell': float(str(item.get('igxe_sell_price', '0') or '0')),
                    'igxe_buy': float(item.get('igxe_buy_price', 0) or 0),
                    'igxe_sell_num': int(item.get('igxe_sell_num', 0) or 0),
                    'igxe_buy_num': int(item.get('igxe_buy_num', 0) or 0),
                    'steam_sell': float(item.get('steam_sell_price', 0) or 0),
                    'steam_buy': float(item.get('steam_buy_price', 0) or 0),
                    'steam_sell_num': int(item.get('steam_sell_num', 0) or 0),
                    'steam_buy_num': int(item.get('steam_buy_num', 0) or 0),
                }
            print(f'[CSQAQ] All prices: {len(result)} items')
            return result
        else:
            print(f'[CSQAQ] All prices failed: code={resp.get("code")}', file=sys.stderr)
    except Exception as e:
        print(f'[CSQAQ] All prices error: {e}', file=sys.stderr)
    return {}

# ═══════════════ CSQAQ 批量查价（50件/次）═══════════════
def fetch_csqaq_batch_prices(hash_names):
    """通过 marketHashName 批量查询价格，每次50件（API限制）。
    Returns: {market_hash_name: {buff_sell, buff_buy, yyyp_sell, steam_buy, ...}}
    """
    if not hash_names:
        return {}

    def _parse_response(resp, result):
        if resp.get('code') in (0, 200) and resp.get('data', {}).get('success'):
            for mhn, info in resp['data']['success'].items():
                result[mhn] = {
                    'buff_sell': float(info.get('buffSellPrice', 0) or 0),
                    'buff_sell_num': int(info.get('buffSellNum', 0) or 0),
                    'yyyp_sell': float(info.get('yyypSellPrice', 0) or 0),
                    'yyyp_sell_num': int(info.get('yyypSellNum', 0) or 0),
                }

    result = {}
    batch_size = 50
    batches = [hash_names[i:i+batch_size] for i in range(0, len(hash_names), batch_size)]
    total_batches = len(batches)
    for bi, batch in enumerate(batches):
        try:
            _parse_response(
                http_post_raw('https://api.csqaq.com/api/v1/goods/getPriceByMarketHashName',
                              {'marketHashNameList': batch},
                              headers={'ApiToken': CSQ_KEY}, timeout=30),
                result)
        except Exception as e:
            print(f'  [CSQAQ] Batch {bi+1}/{total_batches} error: {e}', file=sys.stderr)
        # 批次间延迟，避免触发限流
        if bi < total_batches - 1:
            time.sleep(0.5)
    print(f'[CSQAQ] Batches: {len(result)}/{len(hash_names)} items ({total_batches} batches)')
    return result

# ═══════════════ FETCH ECO FULL LIST ═══════════════
def fetch_eco_full():
    params = {'PartnerId': PARTNER_ID, 'Timestamp': str(int(time.time())), 'GameID': '730'}
    params['Sign'] = sign_eco(params)
    result = http_post_raw('https://openapi.ecosteam.cn/Api/Market/GetHashNameAndPriceList', params, timeout=30)
    if str(result.get('ResultCode')) != '0':
        raise RuntimeError(f'ECO error: {result.get("ResultCode")} {result.get("ResultMsg")}')
    return result.get('ResultData', [])

# ═══════════════ MATCHING ═══════════════
def normalize_name(name):
    """Normalize Chinese item names for fuzzy matching"""
    import re
    s = name.strip()
    # Remove wear suffix in parentheses
    s = re.sub(r'[（(].*?[）)]', '', s).strip()
    # Remove ★
    s = s.replace('★', '').replace('（★）', '').strip()
    return s

def build_name_index(eco_items):
    """Build name→item index from ECO data"""
    idx = {}
    for item in eco_items:
        gn = item.get('GoodsName', '')
        hn = item.get('HashName', '')
        if gn:
            key = normalize_name(gn)
            if key not in idx:
                idx[key] = item
    return idx

# ═══════════════ RECOMMENDATION ENGINE ═══════════════
def generate_recommendations(csqaq_alerts, eco_items):
    eco_idx = build_name_index(eco_items)
    recs = {'momentum': [], 'undervalued': [], 'oversold': [], 'scarce': [], 'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}

    # Merge: add ECO data to CSQAQ items where possible
    merged = []
    for alert in csqaq_alerts:
        key = normalize_name(alert['name'])
        eco_match = eco_idx.get(key)
        entry = {
            'id': alert['id'],
            'name': alert['name'],
            'exterior': alert.get('exterior', ''),
            'price': alert['price'],  # BUFF price
            'rate_1': alert.get('rate_1', 0),
            'rate_7': alert.get('rate_7', 0),
            'rate_30': alert.get('rate_30', 0),
            'img': alert.get('img', ''),
            'buff_sell': alert.get('buff_sell', 0),
            'buff_buy': alert.get('buff_buy', 0),
            'buff_buy_price': alert.get('buff_buy_price', 0),
            'yyyp_sell': alert.get('yyyp_sell', 0),
            'yyyp_buy': alert.get('yyyp_buy', 0),
            'yyyp_price': alert.get('yyyp_price', 0),
            'steam_sell': alert.get('steam_sell', 0),
            'steam_buy': alert.get('steam_buy', 0),
            'steam_buy_price': alert.get('steam_buy_price', 0),
        }
        if eco_match:
            entry['eco_price'] = float(eco_match.get('Price') or 0)
            entry['eco_compre'] = float(eco_match.get('MarketComprePrice') or 0)
            entry['eco_selling'] = int(eco_match.get('SellingTotal') or 0)
            entry['eco_qg_total'] = int(eco_match.get('QGTotal') or 0)
            entry['eco_qg_max'] = float(eco_match.get('QGMaxPrice') or 0)
            entry['hash_name'] = eco_match.get('HashName', '')
        merged.append(entry)

    # Also add ECO items not in CSQAQ (for scarce/undervalued)
    csqaq_keys = {normalize_name(a['name']) for a in csqaq_alerts}
    eco_only = []
    for item in eco_items:
        gn = item.get('GoodsName', '')
        if not gn: continue
        key = normalize_name(gn)
        if key not in csqaq_keys:
            price = float(item.get('Price') or 0)
            compre = float(item.get('MarketComprePrice') or 0)
            selling = int(item.get('SellingTotal') or 0)
            qg_total = int(item.get('QGTotal') or 0)
            if price < 5 or selling <= 0: continue  # skip trivial
            eco_only.append({
                'name': gn,
                'hash_name': item.get('HashName', ''),
                'eco_price': price,
                'eco_compre': compre,
                'eco_selling': selling,
                'eco_qg_total': qg_total,
                'eco_qg_max': float(item.get('QGMaxPrice') or 0),
            })

    # ── 🔥 强势追涨 (Momentum) ──
    for m in merged:
        if m.get('rate_7', 0) > 5 and m.get('rate_1', 0) > 0 and m.get('price', 0) > 50:
            m['_score'] = round(m['rate_7'] + m['rate_1'], 2)
            recs['momentum'].append(m)
    recs['momentum'].sort(key=lambda x: x['_score'], reverse=True)
    recs['momentum'] = recs['momentum'][:20]

    # ── 💎 低估捡漏 (Undervalued / Cross-platform Arbitrage) ──
    # Strategy A: ECO综合价 > 售价 (估值修复空间) — must have BUFF liquidity
    for m in merged + eco_only:
        ep = m.get('eco_price', 0)
        ec = m.get('eco_compre', 0)
        selling = m.get('eco_selling', 0)
        buff_sell = m.get('buff_sell', 0)
        if ep > 50 and ec > ep * 1.05 and ec < ep * 2.0 and selling > 0 and selling < 200 and buff_sell > 0:
            ratio = round(ec / ep, 3)
            m['_score'] = ratio
            m['_reason'] = f'综合价/售价={ratio:.1%}'
            recs['undervalued'].append(m)
    # Strategy B: BUFF求购价 > BUFF售价 (买盘强于卖盘)
    for m in merged:
        bp = m.get('price', 0)
        bbp = m.get('buff_buy_price', 0)
        if bp > 50 and bbp > bp * 1.01:
            premium = round(bbp / bp, 3)
            key = m.get('name', '')
            if not any(r.get('name') == key for r in recs['undervalued']):
                m['_score'] = premium
                m['_reason'] = f'BUFF求购¥{bbp:.0f}>售价¥{bp:.0f} 溢价{premium:.1%}'
                recs['undervalued'].append(m)
    # Strategy C: Steam求购价远高于BUFF (跨平台套利)
    for m in merged:
        bp = m.get('price', 0)
        sbp = m.get('steam_buy_price', 0)
        if bp > 100 and sbp > bp * 1.15:
            premium = round(sbp / bp, 3)
            key = m.get('name', '')
            if not any(r.get('name') == key for r in recs['undervalued']):
                m['_score'] = premium
                m['_reason'] = f'Steam求购¥{sbp:.0f}/BUFF¥{bp:.0f} 跨平台溢价{premium:.0%}'
                recs['undervalued'].append(m)
    recs['undervalued'].sort(key=lambda x: x['_score'], reverse=True)
    recs['undervalued'] = recs['undervalued'][:20]

    # ── 📉 超跌反弹 (Oversold) ──
    for m in merged:
        if m.get('rate_7', 0) < -8 and m.get('eco_qg_total', 0) > 0 and m.get('price', 0) > 50:
            m['_score'] = abs(m['rate_7'])
            recs['oversold'].append(m)
    recs['oversold'].sort(key=lambda x: x['_score'], reverse=True)
    recs['oversold'] = recs['oversold'][:20]

    # ── ⚡ 供不应求 (Supply Squeeze) — CSQAQ 多平台供需 ──
    for m in merged:
        name_lower = m.get('name', '').lower()
        # Skip cases/keys/containers
        if any(kw in name_lower for kw in ('武器箱', '钥匙', '箱', 'key', 'case')):
            continue
        buff_sell = m.get('buff_sell', 0)
        buff_buy = m.get('buff_buy', 0)
        steam_buy = m.get('steam_buy', 0)
        price = m.get('price', 0) or m.get('eco_price', 0)
        if price < 20: continue
        # BUFF 求购/在售比
        if buff_sell > 0 and buff_buy > 0:
            ratio = buff_buy / buff_sell
            if ratio >= 0.15 and buff_sell < 500:
                m['_score'] = round(ratio, 2)
                parts = []
                parts.append(f'BUFF求购{buff_buy}/在售{buff_sell}={ratio:.0%}')
                if steam_buy > 50:
                    parts.append(f'Steam求购{steam_buy}')
                if m.get('yyyp_buy', 0) > 10:
                    parts.append(f'悠悠求购{m["yyyp_buy"]}')
                m['_reason'] = ' · '.join(parts)
                recs['scarce'].append(m)
                continue
        # Steam 求购量异常高（求购>500 且 steam_buy/buff_sell > 5，说明有大量买盘）
        if steam_buy > 500 and buff_sell > 0 and steam_buy / buff_sell < 200:
            m['_score'] = round(steam_buy / buff_sell, 2)
            m['_reason'] = f'Steam求购{steam_buy} · BUFF在售{buff_sell}'
            recs['scarce'].append(m)
    recs['scarce'].sort(key=lambda x: x['_score'], reverse=True)
    recs['scarce'] = recs['scarce'][:20]

    return recs

# ═══════════════ MAIN ═══════════════
def main():
    print('=== CS2 Recommendation Engine ===')

    print('[CSQAQ] Fetching alerts...')
    try:
        alerts = fetch_csqaq_alerts()
        print(f'[CSQAQ] Got {len(alerts)} items')
    except Exception as e:
        print(f'[CSQAQ] FAIL: {e}', file=sys.stderr)
        alerts = []

    print('[ECO] Fetching full price list...')
    try:
        eco_items = fetch_eco_full()
        print(f'[ECO] Got {len(eco_items)} items')
    except Exception as e:
        print(f'[ECO] FAIL: {e}', file=sys.stderr)
        eco_items = []

    if not alerts and not eco_items:
        print('[ERROR] No data available, aborting')
        return

    print('[ENGINE] Generating recommendations...')
    recs = generate_recommendations(alerts, eco_items)
    print(f'  [Momentum] {len(recs["momentum"])}')
    print(f'  [Undervalued] {len(recs["undervalued"])}')
    print(f'  [Oversold] {len(recs["oversold"])}')
    print(f'  [Scarce] {len(recs["scarce"])}')

    # Write to market.json
    market_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'market.json')
    with open(market_path, 'r', encoding='utf-8') as f:
        market = json.load(f)
    market['recommendations'] = recs
    with open(market_path, 'w', encoding='utf-8') as f:
        json.dump(market, f, ensure_ascii=False, indent=2)
    print(f'[OK] Written to market.json')

if __name__ == '__main__':
    main()
