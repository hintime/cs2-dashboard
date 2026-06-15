#!/usr/bin/env python3
"""
追踪 AI 分析引擎
功能：
  1. 保存每日推荐到 rec_tracks.json（累积追踪数据）
  2. 深度分析涨跌原因（对比价格历史 + 市场环境）
  3. 提取教训模式 → tracking_lessons.json（持续进化）
  4. 生成优化后的推荐提示 → 反哺 recommend.py
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = SCRIPT_DIR
DEEPSEEK_KEY = os.environ.get('DEEPSEEK_KEY', 'sk-3a9f8fed7ff94e7398e3a9164807cb24')
# 追踪分析固定用 DeepSeek
AI_KEY = DEEPSEEK_KEY
AI_ENDPOINT = 'https://api.deepseek.com/v1/chat/completions'
MODEL = 'deepseek-v4-flash'

# ── 数据读写 ──

def _load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return None

def _save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_daily_tracks(recommendations):
    """保存今天的推荐到 rec_tracks.json（每天一个快照键）"""
    today = time.strftime('%Y-%m-%d')
    path = os.path.join(DATA_DIR, 'rec_tracks.json')
    tracks = _load_json(path) or {}
    
    # 今天已存在的记录，用当前推荐覆盖（保持最新评分）
    day_items = {}
    for rec in recommendations:
        name = rec.get('name', '')
        if not name:
            continue
        day_items[name] = {
            'name': name,
            'hash_name': rec.get('hash_name', ''),
            'price': rec.get('price', 0) or rec.get('eco_price', 0),
            'score': rec.get('score', 0),
            'tag': rec.get('tag', 'eco'),
            'tag_label': rec.get('tag_label', rec.get('tag', 'eco')),
            'channel_eco': rec.get('channel_eco', 0),
            'channel_buff': rec.get('channel_buff', 0),
            'buff_sell': rec.get('buff_sell', 0),
            'yyyp_sell': rec.get('yyyp_sell', 0),
            'reason': rec.get('_reason', '') or rec.get('reason', '')[:200],
            'recorded_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        }
    
    if day_items:
        tracks[today] = day_items
        _save_json(path, tracks)
        print(f'[TRACK-AI] Saved {len(day_items)} daily tracks to rec_tracks.json')
        return len(day_items)
    return 0

def load_all_tracks():
    """加载所有日期的追踪记录"""
    path = os.path.join(DATA_DIR, 'rec_tracks.json')
    tracks = _load_json(path) or {}
    # 展平为列表，附加日期
    flat = []
    for date_str, items in tracks.items():
        if not isinstance(items, dict):
            continue
        for name, item in items.items():
            if not isinstance(item, dict):
                continue
            flat.append({**item, 'date': date_str})
    return flat

# ── AI 调用 ──

def _call_ai(messages, max_tokens=2048, temperature=0.5, json_mode=False):
    """统一 AI 调用 — 自动切换 DeepSeek/Zhipu（含重试）"""
    key = AI_KEY
    endpoint = AI_ENDPOINT
    
    for attempt in range(3):
        try:
            body = {
                'model': MODEL,
                'messages': messages,
                'max_tokens': max_tokens,
                'temperature': temperature,
                'thinking': {'type': 'enabled'}
            }
            if json_mode:
                body['response_format'] = {'type': 'json_object'}
            
            data = json.dumps(body).encode('utf-8')
            req = urllib.request.Request(
                endpoint,
                data=data,
                headers={
                    'Authorization': f'Bearer {key}',
                    'Content-Type': 'application/json'
                }
            )
            resp = urllib.request.urlopen(req, timeout=90)
            result = json.loads(resp.read().decode('utf-8'))
            content = result['choices'][0]['message'].get('content', '')
            return content
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = (attempt + 1) * 12
                print(f'[TRACK-AI] 429 rate limited, waiting {wait}s (attempt {attempt+1}/3)...')
                time.sleep(wait)
            else:
                print(f'[TRACK-AI] HTTP {e.code}: {e}', file=sys.stderr)
                if attempt == 2:
                    return None
                time.sleep(5)
        except Exception as e:
            print(f'[TRACK-AI] Error: {e}', file=sys.stderr)
            if attempt == 2:
                return None
            time.sleep(5)
    return None

# ── 核心分析 ──

def analyze_performance(tracks, price_context=None):
    """
    深度分析追踪表现
    tracks: [{name, date, price, score, tag, buff_sell, yyyp_sell, ...}]
    price_context: 从 price_history.db 获取的额外价格走势（可选）
    返回: 结构化分析结果
    """
    if not tracks or len(tracks) < 3:
        print('[TRACK-AI] Too few tracks (<3), skipping analysis')
        return None
    
    # 分类统计
    total = len(tracks)
    dates = sorted(set(t.get('date', '') for t in tracks))
    eco_items = [t for t in tracks if t.get('tag') == 'eco']
    buff_items = [t for t in tracks if t.get('tag') == 'buff']
    
    # 按价格区间分组
    cheap = [t for t in tracks if t.get('price', 0) < 10]
    mid = [t for t in tracks if 10 <= t.get('price', 0) < 100]
    high = [t for t in tracks if t.get('price', 0) >= 100]
    
    # 构建分析文本
    items_text = []
    for t in tracks[:20]:  # 最多20件（省钱）
        p = t.get('price', 0)
        s = t.get('score', 0)
        bs = t.get('buff_sell', 0)
        ys = t.get('yyyp_sell', 0)
        ch_eco = t.get('channel_eco', 0)
        ch_buff = t.get('channel_buff', 0)
        reason = (t.get('reason', '') or '')[:80]
        
        # 计算溢价率
        premium = ''
        if p > 0 and bs > 0:
            prem = (bs - p) / p * 100
            premium = f' 溢价{prem:+.1f}%'
        elif p > 0 and ys > 0:
            prem = (ys - p) / p * 100
            premium = f' 溢价{prem:+.1f}%(YY)'
        
        items_text.append(
            f"{t.get('name','?')[:35]} | ¥{p:.0f} | 分{s:.0f} | {t.get('tag_label','')} "
            f"| ECO分{ch_eco} BUFF分{ch_buff}{premium} | {reason}"
        )
    
    # 获取市场背景
    market_bg = _get_market_background()
    
    prompt = f"""分析以下CS2饰品推荐追踪数据，深挖涨跌根因并提炼教训。

【追踪概况】共{total}件推荐，{len(dates)}天（{dates[0]}~{dates[-1] if dates else 'N/A'}）
ECO推荐{len(eco_items)}件，BUFF推荐{len(buff_items)}件
低价(<¥10):{len(cheap)}件 中价(¥10-100):{len(mid)}件 高价(>¥100):{len(high)}件

【推荐清单】(名/价/分/来源/维度分/溢价/理由)
{chr(10).join(items_text)}

【市场背景】{market_bg}

请严格返回JSON（不要markdown）:
{{
  "overview": {{
    "verdict": "整体评价(1句话,15字内)",
    "success_pattern": "成功推荐的共性特征(40字内)",
    "failure_pattern": "失败推荐的共性特征(40字内)",
    "confidence_trend": "上升/下降/持平",
    "market_signal": "当前市场信号(一句话)"
  }},
  "lessons": [
    {{"id": "L01", "category": "timing/market/source/scoring", "lesson": "具体教训(30字内)", "impact": "高/中/低", "action": "如何改进(30字内)"}}
  ],
  "scoring_feedback": {{
    "eco_weight_advice": "+X%/-X%/不变(ECO评分权重建议)",
    "buff_weight_advice": "+X%/-X%/不变(BUFF评分权重建议)",
    "premium_threshold_advice": "溢价率阈值调整建议(20字内)",
    "liquidity_advice": "流动性权重调整建议(20字内)"
  }},
  "recommendation_prompt_tweak": "推荐理由生成优化建议(50字内，例如:减少XX维度，增加XX考虑)"
}}"""

    print(f'[TRACK-AI] Analyzing {total} tracks ({len(items_text)} items)...')
    result = _call_ai([
        {'role': 'system', 'content': '你是CS2饰品投资策略师。根据追踪数据反推推荐策略得失。只返回JSON。'},
        {'role': 'user', 'content': prompt}
    ], max_tokens=1200, temperature=0.4, json_mode=True)
    
    if not result:
        print('[TRACK-AI] AI analysis failed')
        return None
    
    try:
        analysis = json.loads(result)
        analysis['meta'] = {
            'total_tracks': total,
            'date_range': f"{dates[0]}~{dates[-1]}" if dates else 'N/A',
            'analyzed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'model': MODEL
        }
        return analysis
    except json.JSONDecodeError:
        # 尝试提取JSON
        start = result.find('{')
        end = result.rfind('}') + 1
        if start >= 0 and end > start:
            try:
                return json.loads(result[start:end])
            except:
                pass
        print(f'[TRACK-AI] Failed to parse AI response as JSON')
        return None

def _get_market_background():
    """获取当前市场背景数据"""
    bg_parts = []
    
    # 从 market_scan.json 获取
    scan = _load_json(os.path.join(DATA_DIR, 'market_scan.json'))
    if scan:
        bg_parts.append(f"全量{scan.get('total','?')}件,追踪{scan.get('tracked','?')}件,均价¥{scan.get('avg_p',0):.0f}")
        movers = scan.get('movers', {})
        gainers = movers.get('gainers', [])
        losers = movers.get('losers', [])
        if gainers:
            bg_parts.append(f"领涨: {gainers[0].get('n','')[:15]} +{gainers[0].get('r7',0)}%")
        if losers:
            bg_parts.append(f"领跌: {losers[0].get('n','')[:15]} {losers[0].get('r7',0)}%")
    
    # 从 eco_tracked.json 获取覆盖率
    eco = _load_json(os.path.join(DATA_DIR, 'eco_tracked.json'))
    if eco and isinstance(eco, list):
        buff_ok = sum(1 for it in eco if (it.get('buff_sell', 0) or 0) > 0)
        yy_ok = sum(1 for it in eco if (it.get('yyyp_sell', 0) or 0) > 0)
        bg_parts.append(f"BUFF覆盖{buff_ok}/{len(eco)}件,YY覆盖{yy_ok}/{len(eco)}件")
    
    # 从 alerts 获取波动
    market = _load_json(os.path.join(DATA_DIR, 'market.json'))
    if market:
        alerts = market.get('alerts', [])
        if alerts and isinstance(alerts, list):
            surge = [a for a in alerts if a.get('alert_type') == 'surge']
            dump = [a for a in alerts if a.get('alert_type') == 'dump']
            if surge:
                bg_parts.append(f"急涨信号{len(surge)}条")
            if dump:
                bg_parts.append(f"急跌信号{len(dump)}条")
    
    return '; '.join(bg_parts) if bg_parts else '无市场背景数据'

# ── 教训积累 ──

def _compute_track_stats():
    """计算当前追踪数据的成功率（用于对比进化效果）"""
    tracks = load_all_tracks()
    if not tracks:
        return {'total': 0, 'profitable': 0, 'rate': 0}
    
    # 从 price_summary 获取最新价格
    ps = _load_json(os.path.join(DATA_DIR, 'price_summary.json')) or {}
    
    profitable = 0
    priced = 0
    for t in tracks:
        rec_price = t.get('price', 0)
        if rec_price <= 0:
            continue
        # 查最新价格：先用 hash_name (英语)，再用 name (中文)
        pdata = ps.get(t.get('hash_name', ''), None) or ps.get(t.get('name', ''), {})
        latest_prices = pdata.get('prices', []) if isinstance(pdata, dict) else []
        cur_price = latest_prices[-1] if latest_prices else 0
        if cur_price > 0:
            priced += 1
            if cur_price > rec_price:
                profitable += 1
    
    rate = round(profitable / priced * 100, 1) if priced > 0 else 0
    return {'total': len(tracks), 'priced': priced, 'profitable': profitable, 'rate': rate}

LESSONS_PATH = os.path.join(DATA_DIR, 'tracking_lessons.json')

def extract_lessons(analysis):
    """从分析结果提取教训，累积到 tracking_lessons.json"""
    if not analysis or 'lessons' not in analysis:
        return
    
    lessons_db = _load_json(LESSONS_PATH) or {
        'version': 1,
        'accumulated_since': time.strftime('%Y-%m-%d'),
        'total_analyses': 0,
        'lessons': [],
        'history': [],
        'analysis_history': []  # 每次分析的 overview + scoring_feedback（进化轨迹）
    }
    
    lessons_db['total_analyses'] += 1
    lessons_db['last_updated'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    lessons_db['last_track_count'] = len(load_all_tracks())  # 记录此时track数，用于下次判断是否需要分析
    
    # 记录本次分析的 overview 和 scoring_feedback（进化轨迹）
    analysis_snapshot = {
        'seq': lessons_db['total_analyses'],
        'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'overview': analysis.get('overview', {}),
        'scoring_feedback': analysis.get('scoring_feedback', {}),
        'prompt_tweak': analysis.get('recommendation_prompt_tweak', ''),
        'stats': _compute_track_stats()  # 当前追踪成功率
    }
    analysis_history = lessons_db.get('analysis_history', [])
    analysis_history.append(analysis_snapshot)
    # 保留最近 20 次
    if len(analysis_history) > 20:
        analysis_history = analysis_history[-20:]
    lessons_db['analysis_history'] = analysis_history
    
    # 合并新教训（去重 + 按 impact 排序）
    new_lessons = analysis.get('lessons', [])
    existing_ids = {l.get('id', '') for l in lessons_db['lessons']}
    
    for lesson in new_lessons:
        lid = lesson.get('id', '')
        if not lid:
            continue
        # 新教训
        if lid not in existing_ids:
            lesson['added_at'] = time.strftime('%Y-%m-%d')
            lesson['confirmed'] = 1
            lessons_db['lessons'].append(lesson)
            existing_ids.add(lid)
        else:
            # 已存在 → 确认次数+1
            for existing in lessons_db['lessons']:
                if existing.get('id') == lid:
                    existing['confirmed'] = existing.get('confirmed', 1) + 1
                    existing['last_seen'] = time.strftime('%Y-%m-%d')
                    break
    
    # 排序：确认次数高的排前面
    lessons_db['lessons'].sort(key=lambda l: l.get('confirmed', 1), reverse=True)
    
    # 保留最近10条活跃，其余归档
    if len(lessons_db['lessons']) > 10:
        archived = lessons_db['lessons'][10:]
        lessons_db['history'].extend(archived)
        lessons_db['lessons'] = lessons_db['lessons'][:10]
    
    _save_json(LESSONS_PATH, lessons_db)
    print(f'[TRACK-AI] Lessons: {len(lessons_db["lessons"])} active, {len(lessons_db["history"])} archived')

def get_lessons_for_prompt():
    """获取当前教训，格式化为可注入推荐Prompt的文本"""
    lessons_db = _load_json(LESSONS_PATH)
    if not lessons_db or not lessons_db.get('lessons'):
        return ''
    
    lines = ['\n【历史追踪教训（来自AI分析）】']
    for l in lessons_db['lessons'][:5]:
        conf = l.get('confirmed', 1)
        stars = '⭐' * min(conf, 3)
        lines.append(f"- {stars} [{l.get('category','')}] {l.get('lesson','')} → {l.get('action','')}")
    
    return '\n'.join(lines)

# ── 单物品深度分析 ──

def analyze_single_mover(item_name, rec_price, current_price, tag, price_history):
    """
    深度分析单个物品的涨跌原因
    price_history: [(date, price), ...] 历史价格序列
    返回: 简短的分析文本
    """
    if not price_history or len(price_history) < 3:
        return None
    
    change = (current_price - rec_price) / rec_price * 100 if rec_price > 0 else 0
    direction = '涨' if change > 0 else '跌'
    
    # 找历史高点和低点
    prices = [p[1] for p in price_history[-30:]]
    if len(prices) >= 3:
        hist_high = max(prices)
        hist_low = min(prices)
        hist_avg = sum(prices) / len(prices)
    else:
        hist_high = hist_low = hist_avg = rec_price
    
    prompt = f"""分析CS2饰品价格变动原因:
物品: {item_name[:40]}
推荐价: ¥{rec_price:.1f} → 当前价: ¥{current_price:.1f} ({change:+.1f}%)
标签: {tag}
历史区间: ¥{hist_low:.0f} ~ ¥{hist_high:.0f} (均价¥{hist_avg:.0f})
最近走势: {', '.join(f'¥{p:.0f}' for _,p in price_history[-5:])}

{direction}幅{abs(change):.1f}%，用一句话(40字内)分析可能原因和市场含义。纯文本，不要JSON。"""

    result = _call_ai([
        {'role': 'system', 'content': '你是CS2饰品市场分析师。简洁精准。'},
        {'role': 'user', 'content': prompt}
    ], max_tokens=200, temperature=0.3)
    
    return result

# ── 反哺推荐逻辑 ──

def generate_recommendation_feedback(tracks):
    """
    基于追踪数据生成推荐逻辑优化建议
    返回: 可注入推荐Prompt的优化文本
    """
    if not tracks or len(tracks) < 5:
        return ''
    
    # 这里会被 analyze_performance 自动调用，结果在 lessons 中
    lessons = _load_json(LESSONS_PATH) or {}
    if not lessons.get('lessons'):
        return ''
    
    active = lessons.get('lessons', [])[:5]
    lines = ['\n【AI追踪反馈 — 推荐策略持续优化】']
    for l in active:
        cat = l.get('category', 'general')
        cat_label = {'timing': '时机', 'market': '市场', 'source': '数据源', 'scoring': '评分'}.get(cat, cat)
        lines.append(f"- [{cat_label}] {l.get('lesson','')} | 改进: {l.get('action','')}")
    
    return '\n'.join(lines)

# ── CI 入口 ──

def main(tracks=None):
    """
    CI管线入口 — 精打细算：只在数据有意义变化时才调用 DeepSeek
    规则：
      - 每日最多分析 1 次（同一天内跳过）
      - track 数量增长 <20% 时跳过（数据没大变）
      - 距离上次分析 <8 小时跳过（避免短时间重复）
    """
    if tracks is None:
        tracks = load_all_tracks()
    
    if not tracks or len(tracks) < 3:
        print(f'[TRACK-AI] Insufficient tracks ({len(tracks) if tracks else 0}), skip')
        return None
    
    # ── 成本控制：检查是否需要分析 ──
    today = time.strftime('%Y-%m-%d')
    lessons_db = _load_json(LESSONS_PATH) or {}
    last_analysis_ts = lessons_db.get('last_updated', '')
    last_analysis_count = lessons_db.get('last_track_count', 0)
    
    # 今天已分析过 → 跳过
    if last_analysis_ts.startswith(today):
        print(f'[TRACK-AI] Already analyzed today ({today}), skip (save API cost)')
        return None
    
    # 距离上次分析 <8 小时 → 跳过
    if last_analysis_ts:
        try:
            last_dt = time.strptime(last_analysis_ts[:19], '%Y-%m-%dT%H:%M:%S')
            hours_ago = (time.time() - time.mktime(last_dt)) / 3600
            if hours_ago < 8:
                print(f'[TRACK-AI] Last analysis {hours_ago:.1f}h ago (<8h), skip')
                return None
        except:
            pass
    
    # track 数量增长 <20% → 跳过（数据没大变）
    if last_analysis_count > 0:
        growth = (len(tracks) - last_analysis_count) / last_analysis_count * 100
        if growth < 20:
            print(f'[TRACK-AI] Track growth only {growth:.0f}% (<20%), skip analysis')
            return None
    
    print(f'[TRACK-AI] Starting analysis of {len(tracks)} tracks...')
    
    # 1. 深度分析
    analysis = analyze_performance(tracks)
    
    if analysis:
        # 2. 保存分析结果
        out_path = os.path.join(DATA_DIR, 'tracking_analysis.json')
        _save_json(out_path, analysis)
        print(f'[TRACK-AI] Analysis saved to tracking_analysis.json')
        
        # 3. 提取教训
        extract_lessons(analysis)
        
        # 4. 输出关键发现
        overview = analysis.get('overview', {})
        print(f'[TRACK-AI] → {overview.get("verdict", "N/A")}')
        print(f'[TRACK-AI] → 成功模式: {overview.get("success_pattern", "N/A")}')
        print(f'[TRACK-AI] → 失败模式: {overview.get("failure_pattern", "N/A")}')
        print(f'[TRACK-AI] → 市场信号: {overview.get("market_signal", "N/A")}')
        est_tokens = len(tracks) * 50 + 1200  # 粗略估算 input+output
        print(f'[TRACK-AI] 💰 估算消耗 ~{est_tokens} tokens (约¥{est_tokens/1000000*1.1:.4f})')
    else:
        print(f'[TRACK-AI] ⏭ 跳过分析（省钱模式：每24h最多1次）')
    
    return analysis

if __name__ == '__main__':
    main()
