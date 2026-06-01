#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只跑 AI 生成部分，不动数据管线"""
import os, sys, json, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 强制 UTF-8
os.environ['PYTHONIOENCODING'] = 'utf-8'

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))
ZHIPU_KEY = os.environ.get('ZHIPU_KEY', '981fb5b064af4d86896d804ddea2acbc.VmZsKxfM4fL4vefz')

def read_json(p):
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)

def write_json(p, d):
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def call_glm(prompt, system=None, max_tokens=2000, temperature=0.5):
    messages = []
    if system:
        messages.append({'role': 'system', 'content': system})
    messages.append({'role': 'user', 'content': prompt})
    data = json.dumps({
        'model': 'glm-4.7-flash',
        'messages': messages,
        'max_tokens': max_tokens,
        'temperature': temperature
    }).encode('utf-8')
    req = urllib.request.Request(
        'https://open.bigmodel.cn/api/paas/v4/chat/completions',
        data=data,
        headers={'Authorization': f'Bearer {ZHIPU_KEY}', 'Content-Type': 'application/json'}
    )
    resp = urllib.request.urlopen(req, timeout=45)
    r = json.loads(resp.read().decode('utf-8'))
    return r['choices'][0]['message']['content'].strip()

# ── 1. AI 市场洞察 ──
print('='*50)
print('[1/3] AI 市场洞察...')
try:
    scan = read_json(os.path.join(DATA_DIR, 'market_scan.json'))
    total = scan.get('total', 0); avg_p = scan.get('avg_p', 0); median_p = scan.get('median_p', 0)
    min_p = scan.get('min_p', 0); max_p = scan.get('max_p', 0)
    categories = scan.get('categories', {}); tiers = scan.get('tiers', {})
    movers = scan.get('movers', {})
    gainers = movers.get('gainers', [])[:5]; losers = movers.get('losers', [])[:5]
    top_sell = scan.get('top_sell', [])[:3]
    cat_text = ' | '.join([f'{k}:{v}' for k,v in list(categories.items())[:6]])
    tier_text = ' | '.join([f'{k}:{v}' for k,v in tiers.items()])
    gain_text = '、'.join([f"{g['n'][:20]}+{g['r7']}%" for g in gainers])
    lose_text = '、'.join([f"{l['n'][:20]}{l['r7']}%" for l in losers])
    hot_text = '、'.join([f"{s['n'][:15]}{s['s']}" for s in top_sell])
    prompt = (
        f'你是CS2饰品市场AI分析师。根据以下全量数据给出一段150字市场洞察：\n'
        f'全量{total}件，均价{avg_p:.0f}，中位{median_p:.0f}，最低{min_p:.2f}，最高{max_p:.0f}\n'
        f'品类：{cat_text}\n价格分布：{tier_text}\n'
        f'涨幅TOP5：{gain_text}\n跌幅TOP5：{lose_text}\n最热：{hot_text}\n'
        f'要求：分析市场情绪、资金流向、风险点。简洁专业，100-150字。'
    )
    insight = call_glm(prompt, max_tokens=2000)
    result = {'date': time.strftime('%Y-%m-%d %H:%M'), 'insight': insight,
              'stats': {'total': total, 'avg_p': avg_p, 'median_p': median_p}}
    write_json(os.path.join(DATA_DIR, 'ai_market_insight.json'), result)
    print(f'  ✅ 生成 {len(insight)} 字: {insight[:80]}...')
except Exception as e:
    print(f'  ❌ 失败: {e}')

# ── 2. AI 异动分析 ──
print('[2/3] AI 异动分析...')
try:
    bh = read_json(os.path.join(DATA_DIR, 'buff_history.json'))
    dates = sorted(bh.keys())
    if len(dates) >= 2:
        now = dates[-1]
        # 找 24 小时前的快照，避免同日对比
        prev = dates[-2]
        now_ts = now.replace('T', ' ')[:13]  # rough
        for d in reversed(dates[:-1]):
            prev = d
            if d[:10] != now[:10]:  # 不同日期
                break
        changes = []
        for name, info in bh[now].items():
            if name not in bh[prev]: continue
            now_num = info.get('buff_sell_num', 0) or info.get('yyyp_sell_num', 0)
            prev_num = bh[prev][name].get('buff_sell_num', 0) or bh[prev][name].get('yyyp_sell_num', 0)
            if prev_num > 0 and now_num > 0:
                pct = (now_num - prev_num) / prev_num * 100
                if abs(pct) > 10:
                    changes.append((name, pct, now_num, prev_num))
        if changes:
            changes.sort(key=lambda x: abs(x[1]), reverse=True)
            top = changes[:5]
            items_text = '\n'.join([f'{n}: 在售量 {pr}→{nr} ({pct:+.0f}%)' for n, pct, nr, pr in top])
            prompt = f'CS2饰品在售量异动检测，以下饰品在售量变化超过10%：\n{items_text}\n请分析这些异动可能的原因和影响，100字以内。'
            analysis = call_glm(prompt, system='你是CS2饰品市场分析师。简洁分析在售量异动原因。', max_tokens=2000)
            result = {'anomalies': [{'name': n, 'pct': round(pct, 1)} for n, pct, _, _ in top], 'analysis': analysis}
            write_json(os.path.join(DATA_DIR, 'ai_anomaly.json'), result)
            print(f'  ✅ 分析 {len(top)} 件异动: {analysis[:80]}...')
        else:
            print('  ⚠️ 无显著异动（>10%）')
    else:
        print('  ⚠️ buff_history.json 数据不足')
except Exception as e:
    print(f'  ❌ 失败: {e}')

# ── 3. AI 空投监控 ──
print('[3/3] AI 空投监控...')
try:
    news_path = os.path.join(DATA_DIR, 'news.json')
    if os.path.exists(news_path):
        news_data = read_json(news_path)
        items = news_data if isinstance(news_data, list) else (news_data.get('announcements', []) or news_data.get('news', []) or [])
        headlines = []
        for n in items[:5]:
            if isinstance(n, dict):
                title = n.get('title', '') or n.get('headline', '')
                body = (n.get('contents', '') or n.get('body', '') or '')[:100]
                headlines.append(f"- {title}: {body}")
            elif isinstance(n, str):
                headlines.append(f"- {n[:120]}")
        if headlines:
            news_text = '\n'.join(headlines[:5])
            prompt = (
                f'你是CS2饰品市场分析师。以下是Steam CS2最新公告，请分析对饰品市场的影响：\n'
                f'{news_text}\n\n'
                f'用中文给出：1)一句话核心影响 2)利好哪些品类 3)利空哪些品类 4)持仓建议。总计120字以内。'
                f'若公告与饰品无关，回复"本期公告对饰品市场无直接影响。"'
            )
            impact = call_glm(prompt, max_tokens=2000)
            result = {'date': time.strftime('%Y-%m-%d %H:%M'), 'impact': impact,
                      'headlines': [h[:80] for h in headlines[:3]]}
            write_json(os.path.join(DATA_DIR, 'ai_news_impact.json'), result)
            print(f'  ✅ 生成 {len(impact)} 字: {impact[:80]}...')
        else:
            print('  ⚠️ news.json 无有效标题')
    else:
        print('  ⚠️ news.json 不存在')
except Exception as e:
    print(f'  ❌ 失败: {e}')

print('='*50)
print('AI 生成完成！')
