#!/usr/bin/env python3
"""生成 market_scan.json（全市场扫描快照 + 分类统计 + 涨跌榜）"""
import json, os, sys, time

DATA_DIR = os.path.dirname(os.path.abspath(__file__))

def read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    # 自动修复 git 冲突标记
    if '<<<<<<<' in content and '>>>>>>>' in content:
        content = content.split('>>>>>>>')[0].split('=======')[0].replace('<<<<<<< HEAD', '')
        content = content.strip()
    # 尝试解析，失败则自动修复截断
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        # 检查是否是截断（文件末尾不完整）
        if e.pos >= len(content.rstrip()) - 50:
            # 截断修复：计算未闭合的括号数并补全
            before = content[:e.pos]
            open_b = before.count('{') - before.count('}')
            open_a = before.count('[') - before.count(']')
            content = content.rstrip()
            if content.endswith(','):
                content = content[:-1].rstrip()
            content += '\n' + '  ' * (open_a) + ']' * open_a + '}' * open_b
            try:
                fixed = json.loads(content)
                # 写回修复后的文件
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f'[AUTO-FIX] {os.path.basename(path)} 截断已修复 (补充 {open_a}个] {open_b}个}})')
                return fixed
            except:
                pass
        raise e

def write_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

# ══════════════ 筛选规则：统一到 item_filter（单一来源）══════════════
# 2026-09-20：原来这里自带一份 classify/_is_valid_scan_item，与 update.py 里的
# _EXCLUDE_PREFIXES/_EXCLUDE_EXTERIORS 是两套不一致的规则，而**数据库写入**和
# **异动榜**两处根本没有过滤 —— 导致 db 里躺着 811 个不该在的标的（15.5%），
# 且它们会直接出现在涨跌榜上。
# 现在统一走 item_filter，并修正了「贴纸胶囊被误判成探员」的 bug。
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)
from item_filter import classify, is_excluded, SKIP_CATS  # noqa: E402


def is_boring(name):
    """中文名兜底：原实现的关键词表（保留，与 item_filter 互为补充）。

    ⚠ 2026-09-20 修：原来裸用 `'印花'` / `'Pin'` 这类短词，会把**皮肤名**误杀：
      · `Desert Eagle | Printstream` 中文「沙漠之鹰 | **印花集**」   → 被"印花"误杀
      · `CZ75-Auto | Imprint`       中文「CZ75自动型 | **印花板**」 → 被"印花"误杀
      · `SSG 08 | Sea Calico`       中文「SSG 08 | 海滨**印花**」   → 被"印花"误杀
      · `★ Sport Gloves | Creme Pinstripe` 含 "**Pin**stripe"      → 被"Pin"误杀
    改法：这些词要求后面紧跟 ` | `（真物品名形如「印花 | 手套就位」）。
    皮肤名不会是这个格式，所以不会误伤。
    """
    kw = ['武器箱', ' Capsule', '胶囊', '钥匙', 'Terminal', 'Music Kit',
          'Charm', 'Sticker', 'Patch', '布章']
    kw_sep = ['印花 |', '印花板 |', '涂鸦 |', '挂件 |', '音乐盒 |']
    return (any(k in (name or '') for k in kw)
            or any(k in (name or '') for k in kw_sep))


def _is_valid_scan_item(it):
    """全量扫描应排除的品类 / 磨损 / 前缀。

    两道判断都过才算有效：
      ① item_filter.is_excluded —— 前缀(StatTrak/Souvenir) + 磨损 + 品类
      ② is_boring(中文名)       —— 中文关键词兜底（英文名可能看不出来）
    """
    if not isinstance(it, dict):
        return False
    hn = it.get('HashName', '')
    gn = it.get('GoodsName') or ''
    if is_excluded(hn, gn):
        return False
    if is_boring(hn + gn):
        return False
    return True

def main():
    cat = read_json(os.path.join(DATA_DIR, 'eco_catalog.json'))
    if not isinstance(cat, list):
        print('[SCAN] eco_catalog.json not found or invalid')
        return

    # 先过滤全量数据
    valid = [it for it in cat if _is_valid_scan_item(it)]
    print(f'[SCAN] Total: {len(cat)}, Valid: {len(valid)}')

    prices = [it.get('Price', 0) for it in valid if isinstance(it, dict) and it.get('Price', 0) > 0]
    tiers = {'<10': 0, '10-50': 0, '50-200': 0, '200-1000': 0, '1000+': 0}
    for p in prices:
        if p < 10: tiers['<10'] += 1
        elif p < 50: tiers['10-50'] += 1
        elif p < 200: tiers['50-200'] += 1
        elif p < 1000: tiers['200-1000'] += 1
        else: tiers['1000+'] += 1

    # 分类统计
    cat_stats = {}
    for it in valid:
        if not isinstance(it, dict): continue
        hn = it.get('HashName', '')
        c = classify(hn)
        if c not in cat_stats:
            cat_stats[c] = {'count': 0, 'total_price': 0, 'price_count': 0}
        cat_stats[c]['count'] += 1
        p = it.get('Price', 0) or 0
        if p > 0:
            cat_stats[c]['total_price'] += p
            cat_stats[c]['price_count'] += 1

    # 精简分类输出
    cat_labels = {'weapon': '武器', 'knife': '刀', 'glove': '手套', 'sticker': '贴纸',
                  'case': '箱子', 'musickit': '音乐盒', 'charm': '挂件', 'graffiti': '涂鸦',
                  'agent': '探员', 'patch': '布章', 'other': '其他'}
    categories = {}
    for k, v in cat_stats.items():
        if k in SKIP_CATS:
            continue
        label = cat_labels.get(k, k)
        categories[label] = {
            'count': v['count'],
            'avg_p': round(v['total_price'] / v['price_count'], 1) if v['price_count'] > 0 else 0
        }

    # 在售TOP10（从有效数据中取）
    with_sell = [it for it in valid if isinstance(it, dict) and it.get('SellingTotal', 0) > 0]
    by_sell = sorted(with_sell, key=lambda x: x.get('SellingTotal', 0), reverse=True)[:10]
    top_sell = [{'n': (it.get('GoodsName') or it.get('HashName', ''))[:30], 's': it.get('SellingTotal', 0), 'p': it.get('Price', 0)} for it in by_sell]

    # 涨跌榜（从 SQLite 计算，不依赖外部 API）
    movers = []
    # 构建 英文→中文 映射
    name_map = {}
    # ★ 在售量映射（流动性过滤用；SellingTotal 就是"在售数量"）
    supply_map = {}
    for it in cat:
        hn = it.get('HashName', '')
        gn = it.get('GoodsName', '')
        if hn and gn:
            name_map[hn] = gn
        if hn:
            try:
                supply_map[hn] = int(it.get('SellingTotal') or 0)
            except (TypeError, ValueError):
                supply_map[hn] = 0

    # ── 涨跌榜过滤阈值（2026-09-20 加，义轩定）──
    # 背景：原来的榜单被两类垃圾污染 —— ① 9 块钱的物品（0.1 元波动就是 10% 涨幅）
    # ② 价格离谱的异常记录（如"手套"标价 28 万）。加了下面三道门槛后榜单才有参考价值。
    MIN_PRICE = 10.0      # 最小价格（元）：低于此值百分比噪声太大
    MAX_CHG = 100.0       # 单次变动上限（%）：超过视为异常（数据错误 / 异常挂牌）
    MIN_SUPPLY = 100      # 最小在售量：流动性太差的物品价格不可信

    try:
        import price_db
        ph = price_db.get_movers_data()
        gains = []
        # ⚠ 注意：这里比的是「约 1 天前」的价格（cutoff = now-86400），
        #   即 **1 日涨跌**；但输出字段历史上叫 `r7`（前端在用它），故保持不变，
        #   仅在此说明以免误解（改字段名会牵动 report.html）。
        cutoff = time.time() - 86400  # 1天前
        stat = {'cat': 0, 'price': 0, 'chg': 0, 'step': 0, 'supply': 0, 'passed': 0}
        for name, h in ph.items():
            if not isinstance(h, list): continue
            eco_prices = [(e.get('t',''), e.get('p',0)) for e in h if isinstance(e, dict) and e.get('p', 0) > 0]
            if len(eco_prices) < 3: continue  # 至少3个数据点
            last_p = eco_prices[-1][1]
            # 找最接近 1 天前的价格
            prev_p = 0
            best_diff = None
            for ts, p in eco_prices[:-1]:
                try:
                    t = time.mktime(time.strptime(ts[:16], '%Y-%m-%dT%H:%M')) if 'T' in ts else time.mktime(time.strptime(ts[:16], '%Y-%m-%d %H:%M'))
                except:
                    continue
                diff = abs(t - cutoff)
                if best_diff is None or diff < best_diff:
                    best_diff = diff
                    prev_p = p
            if prev_p <= 0 or last_p <= 0: continue
            eco_chg = (last_p - prev_p) / prev_p * 100
            if abs(eco_chg) < 0.01: continue
            cn = name_map.get(name, name)
            # ── 门槛 0：品类 / 前缀 / 磨损 —— 统一走 item_filter ──
            #  ★ 原来只按中文关键词过滤，漏掉了 StatTrak、贴纸胶囊（被误判成探员）等
            #    811 个不该出现在榜上的标的。改用 is_excluded 后与采集层规则一致。
            if is_excluded(name, cn) or is_boring(name + cn):
                stat['cat'] += 1
                continue
            # ── 门槛 1：最小价格 ──
            if last_p < MIN_PRICE:
                stat['price'] += 1
                continue
            # ── 门槛 2a：1 日涨跌超限（日线级异常）──
            if abs(eco_chg) > MAX_CHG:
                stat['chg'] += 1
                continue
            # ── 门槛 2b：相邻采样跳变超限（★ "单次变动" —— 抓数据错误/异常挂牌）──
            #   例：某"手套"标价 288888，就是靠这条与门槛 3 一起挡住的
            max_step = 0.0
            for (_, p1), (_, p2) in zip(eco_prices, eco_prices[1:]):
                if p1 > 0:
                    step = abs(p2 - p1) / p1 * 100
                    if step > max_step:
                        max_step = step
            if max_step > MAX_CHG:
                stat['step'] += 1
                continue
            # ── 门槛 3：流动性 ──
            if supply_map.get(name, 0) <= MIN_SUPPLY:
                stat['supply'] += 1
                continue
            stat['passed'] += 1
            gains.append((cn[:24], round(eco_chg, 1), last_p))
        gains.sort(key=lambda x: x[1], reverse=True)
        gainers = [{'n': g[0], 'r7': g[1], 'p': g[2]} for g in gains if g[1] > 0][:10]
        # 显式按涨幅升序取最跌的 10 个（原写法 [-10:][::-1] 依赖上游排序方向，脆弱）
        neg = sorted([g for g in gains if g[1] < 0], key=lambda x: x[1])
        losers = [{'n': g[0], 'r7': g[1], 'p': g[2]} for g in neg[:10]]
        movers = {'gainers': gainers, 'losers': losers}
        print('[SCAN] movers 过滤：品类/前缀/磨损 剔除 %d ｜ 价格<%g 剔除 %d ｜ '
              '日涨跌>%g%% 剔除 %d ｜ 采样跳变>%g%% 剔除 %d ｜ 在售<=%d 剔除 %d ｜ 通过 %d'
              % (stat['cat'], MIN_PRICE, stat['price'], MAX_CHG, stat['chg'],
                 MAX_CHG, stat['step'], MIN_SUPPLY, stat['supply'], stat['passed']))
    except Exception as e:
        print(f'[SCAN] movers error: {e}')

    prices_sorted = sorted(prices)
    n = len(prices_sorted)
    scan = {
        'updated': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'total': len(valid),
        'tracked': len(read_json(os.path.join(DATA_DIR, 'eco_tracked.json'))) if os.path.exists(os.path.join(DATA_DIR, 'eco_tracked.json')) else 0,
        'tiers': tiers,
        'avg_p': round(sum(prices) / len(prices), 2) if prices else 0,
        'median_p': round(prices_sorted[n//2], 2) if n > 0 else 0,
        'min_p': round(prices_sorted[0], 2) if n > 0 else 0,
        'max_p': round(prices_sorted[-1], 2) if n > 0 else 0,
        'top_sell': top_sell,
        'categories': categories,
        'movers': movers,
    }

    write_json(os.path.join(DATA_DIR, 'market_scan.json'), scan)
    print(f'[SCAN] Saved: {len(valid)} items (from {len(cat)}), {len(prices)} with prices, {len(categories)} categories, movers: {bool(movers)}')

if __name__ == '__main__':
    main()
