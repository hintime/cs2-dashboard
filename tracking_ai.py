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
DEEPSEEK_KEY = os.environ.get('DEEPSEEK_KEY', '')
# ⚠ 2026-09-18：原硬编码 DeepSeek（DEEPSEEK_KEY 未配置 → 持续 401，追踪分析停更 3 天）。
#   现统一走 update._ai_call（智谱 GLM / ollama，含云端兜底）；下列常量仅为兼容保留。
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
            # ⚠ 2026-09-18 修复：原字段名 channel_eco/channel_buff 在推荐条目上并不存在
            #   （真实字段是 eco_score/buff_score）→ 历史快照里恒为 0、因子检验随之失效。
            'channel_eco': rec.get('eco_score', rec.get('channel_eco', 0)),
            'channel_buff': rec.get('buff_score', rec.get('channel_buff', 0)),
            # 真实分维度评分 + 信号位（供「因子有效性检验」与「权重实测标定」使用）
            'dims': {
                'eco_score': rec.get('eco_score'),
                'buff_score': rec.get('buff_score'),
                'n_supply': rec.get('n_supply'),
                'n_ref': rec.get('n_ref'),
                'n_steam': rec.get('n_steam'),
                'n_dev_steam': rec.get('n_dev_steam'),
                'n_premium_buff': rec.get('n_premium_buff'),
                'n_premium_yyyp': rec.get('n_premium_yyyp'),
                'n_cov': rec.get('n_cov'),
                'eco_selling': rec.get('eco_selling'),
                'eco_qg_total': rec.get('eco_qg_total'),
                'buff_sell_num': rec.get('buff_sell_num'),
                'yyyp_sell_num': rec.get('yyyp_sell_num'),
                'rate_7': rec.get('rate_7'),
                # 2026-09-18 新增（真实存世量/买盘来源）：不写进 dims 的话，追踪快照抓不到、
                # 未来做因子检验与 Kronos 校准时就用不上。
                'n_supply_real': rec.get('n_supply_real'),
                'supply_chg7': rec.get('supply_chg7'),
                'buff_buy': rec.get('buff_buy'),
                'buff_buy_num': rec.get('buff_buy_num'),
                'buy_src': rec.get('buy_src'),
                'rate_30': rec.get('rate_30'),
            },
            'signals': rec.get('trend_signals') or [],
            'buff_sell': rec.get('buff_sell', 0),
            'yyyp_sell': rec.get('yyyp_sell', 0),
            'reason': rec.get('_reason', '') or (rec.get('reason', '') or '')[:200],
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
    """统一 AI 调用 — 复用 update._ai_call（智谱 GLM / ollama，含云端兜底与重试）。

    ⚠ 2026-09-18 修复：原实现硬编码 DeepSeek 端点 + DEEPSEEK_KEY（未配置）→ 持续 401，
      追踪分析自 09-15 起一直失败，且被"每 24h 最多 1 次"限流锁死，
      导致 tracking_analysis.json / tracking_lessons.json 停更 3 天。
      现复用项目统一 AI 出口，与推荐/洞察等走同一 provider（默认 zhipu glm-4-flash）。
    """
    try:
        import update as _u
        return _u._ai_call(messages, max_tokens=max_tokens, temperature=temperature,
                           json_mode=json_mode, timeout=120)
    except Exception as e:
        print('[TRACK-AI] 统一 AI 出口调用失败: %s' % e, file=sys.stderr)
        return None

# ★ 2026-09-25 二次修正（结论来自实测 probe_plus2.py，别再改回去）：
#   · glm-4-plus / glm-4-air 在本账号上**连 200 token 的空请求都返回 429**（不是参数问题，
#     是没买额度）→ 都不可用；**只有 glm-4-flash 可用**（1.3s 返回，免费档）。
#   · flash 的失效模式：短请求稳，长输出必崩 —— 要求它吐 7 个顶层段的长 JSON 时，
#     它会把字段写成整段散文，并**编造输入里没有的数字**（"胜率从21.1%提升至24.9%"）。
#   ⇒ 因此本模块改成 **多轮小请求**：每轮只答一件事、只回一个小 JSON（≤600 token）；
#     并且 **所有数字都由 Python 先算好**（含 what_if 子集回测），AI 只做解读与判断，
#     从机制上杜绝"AI 编数字"。想换更强的模型，用环境变量 TRACK_AI_MODEL 覆盖。
TRACK_AI_MODEL = os.environ.get('TRACK_AI_MODEL') or 'glm-4-flash'

_SYS = ('你是量化策略复盘分析师，只做统计解读。规则：'
        '①所有结论必须引用输入里给的数字；②禁止复述推荐理由里的字眼；'
        '③禁止"要重视流动性/要多平台信号"这类无法执行的空话；'
        '④禁止编造输入里没有的数字；⑤严格遵守字段长度，只返回JSON。')


def _parse_json_loose(raw):
    """剥离 ```json 围栏 → 截取最外层 {...} → 兜底 None"""
    r = (raw or '').strip()
    if not r:
        return None
    if r.startswith('```'):
        parts = r.split('```')
        if len(parts) >= 2:
            r = parts[1]
        if r.lstrip().lower().startswith('json'):
            r = r.lstrip()[4:]
    cands = [r]
    a, b = r.find('{'), r.rfind('}')
    if a >= 0 and b > a:
        cands.append(r[a:b + 1])
    for c in cands:
        try:
            d = json.loads(c)
            if isinstance(d, dict):
                return d
        except Exception:
            continue
    return None


def _ai_json(user, max_tokens=600, temperature=0.2, tries=2):
    """小 JSON 专用：短 prompt → 短 JSON。失败重试一次后返回 None。"""
    for i in range(tries):
        out = _call_ai([{'role': 'system', 'content': _SYS},
                        {'role': 'user', 'content': user}],
                       max_tokens=max_tokens, temperature=temperature, json_mode=True)
        d = _parse_json_loose(out)
        if d:
            return d
        print('[TRACK-AI] 小请求第%d次未取到JSON：%s'
              % (i + 1, ((out or '').strip().replace('\n', ' ')[:120] or 'EMPTY')), file=sys.stderr)
    return None


def _ai_text(user, max_tokens=400, temperature=0.2, tries=2):
    """纯文本专用：要一段话/一组行，不要 JSON。

    ★ 为什么要有它：实测 flash 在 JSON 模板里看到形如 "35字内" 的占位说明时，
      会**把说明本身当成值**原样返回（出现过 "lesson":"35字内"、premium:"25%"）。
      纯文本没有占位符可抄，格式用示例行给出，稳定性明显更高。
    """
    for i in range(tries):
        out = _call_ai([{'role': 'system', 'content': _SYS},
                        {'role': 'user', 'content': user}],
                       max_tokens=max_tokens, temperature=temperature, json_mode=False)
        if out and out.strip():
            return out
        print('[TRACK-AI] 文本请求第%d次为空' % (i + 1), file=sys.stderr)
    return ''


def _parse_pipe(txt, need):
    """解析 "A|B" / "A|B|C" 行 → {A: [B, C]}；忽略序号、表头、代码围栏。"""
    out = {}
    if not txt:
        return out
    for raw in txt.split('\n'):
        s = raw.strip().lstrip('-•*0123456789.）) ').strip()
        if not s or s.startswith('|') or s.startswith('```') or s.startswith('{') or s.startswith('['):
            continue
        parts = [p.strip() for p in s.split('|')]
        if len(parts) < need:
            continue
        key = parts[0]
        if not key or key in ('因子名', '规则名', '维度'):
            continue
        out[key] = parts[1:1 + (need - 1)]
    return out


def _ai_model_label():
    """返回当前实际 AI 模型名（用于 meta，避免写死过期的 deepseek 常量）。"""
    return TRACK_AI_MODEL


# ── 核心分析 ──


def _auto_verdicts(S):
    """★ 因子判定由规则生成，不依赖 AI（可复现、绝不编数字）。

    判据只看区分度 spread = 高档均值 − 低档均值：
      |spread| < 1.0        → 无效（没有预测力）
      spread  < -1.0        → 反向（选它反而更差）
      1.0 ≤ spread < 3.0    → 偏弱
      spread  ≥ 3.0         → 有效
    """
    S = S or {}
    # 样本不足时全部标记为 weak：页面要显示"样本不足"，不能让它看起来像定论
    weak = (S.get('factor_n') or 0) < 200 or (S.get('factor_held') or 99) < (S.get('window') or 9)
    out = []
    for f in S.get('factors', [])[:10]:
        sp = f.get('spread') or 0.0
        if abs(sp) < 1.0:
            v = '无效'
        elif sp < 0:
            v = '反向'
        elif sp < 3.0:
            v = '偏弱'
        else:
            v = '有效'
        out.append({'f': f['k'], 'v': v, 'spread': sp, 'n': f.get('n'), 'weak': weak,
                    'lo': f.get('lo'), 'hi': f.get('hi'),
                    'wr_lo': f.get('wr_lo'), 'wr_hi': f.get('wr_hi'),
                    'lo_rng': f.get('lo_rng'), 'hi_rng': f.get('hi_rng'),
                    'evidence': '低档 %+.2f%%（胜%.0f%%）→ 高档 %+.2f%%（胜%.0f%%），区分度 %+.2f%%（n=%d）'
                                % (f.get('lo', 0), f.get('wr_lo', 0), f.get('hi', 0),
                                   f.get('wr_hi', 0), sp, f.get('n', 0))})
    return out


def _auto_lessons(S):
    """★ 教训由真实统计生成（不经过 AI），每条都能追溯到具体数字。

    以前让 AI 写教训 → 它只会输出"要综合考虑多平台信号"这类空话；
    现在把统计里的**显著差异**直接写成教训，AI 只负责在旁边补一句解读。
    """
    S = S or {}
    L = []
    tags = S.get('tags') or {}

    def add(lid, cat, lesson, impact, action):
        L.append({'id': lid, 'category': cat, 'lesson': lesson,
                  'impact': impact, 'action': action, 'auto': True})

    # 1) 通道差异 —— 必须用**同批次**证据，否则可能是"某批次行情好"的假象
    if 'eco' in tags and 'buff' in tags:
        e, b = tags['eco'], tags['buff']
        gap = b['wr'] - e['wr']
        if abs(gap) >= 15:
            ch = S.get('cohort') or []
            # 逐月检查：BUFF 是否每个月都赢 ECO
            months = []
            for c in ch:
                tb, te = c['tags'].get('buff'), c['tags'].get('eco')
                if tb and te:
                    months.append('%s %.0f%%vs%.0f%%' % (c['m'][2:], tb['wr'], te['wr']))
            same = len(months) >= 2 and all(
                (c['tags'].get('buff', {}).get('wr', 0) >= c['tags'].get('eco', {}).get('wr', 100))
                for c in ch if c['tags'].get('buff') and c['tags'].get('eco'))
            ev = ('（同批次内一致：%s）' % '、'.join(months)) if months else ''
            add('L-CH', 'scoring',
                'BUFF 通道胜率 %.1f%%（n=%d，均值 %+.2f%%），ECO 通道仅 %.1f%%（n=%d，均值 %+.2f%%）%s'
                % (b['wr'], b['n'], b['avg'], e['wr'], e['n'], e['avg'], ev),
                '高' if same else '中',
                ('BUFF 在每个推荐月都赢 ECO，不是批次假象 → ECO 通道降权、名额向 BUFF 倾斜'
                 if same else '总体有差异但批次内不一致，先别动权重，继续观察'))

    # 2) 最没用的因子（区分度最负）—— 样本不足时必须降级，不能写成定论
    fcts = S.get('factors') or []
    neg = sorted([f for f in fcts if (f.get('spread') or 0) < -1.0],
                 key=lambda x: x['spread'])
    if neg:
        f = neg[0]
        weak = (S.get('factor_n') or 0) < 200
        add('L-NF', 'scoring',
            '%s 区分度 %+.2f%%：低档均值 %+.2f%% 反而高于高档 %+.2f%%%s'
            % (f['k'], f['spread'], f.get('lo', 0), f.get('hi', 0),
               '（⚠样本仅 %d 条，待验证）' % S['factor_n'] if weak else ''),
            '中' if weak else '高',
            ('先不动 %s 的权重，等维度数据攒够 200 条再判' % f['k'] if weak
             else '把 %s 的打分权重降到 0.05 以下，或直接移出打分项' % f['k']))

    # 3) 数据质量因子（覆盖率）是不是也在拖后腿
    cov = next((f for f in fcts if f['k'] == '数据覆盖率'), None)
    if cov:
        add('L-COV', 'source',
            '数据覆盖率区分度 %+.2f%%：覆盖率低档 %+.2f%% vs 高档 %+.2f%%'
            % (cov['spread'], cov.get('lo', 0), cov.get('hi', 0)),
            '中' if abs(cov['spread']) >= 1.0 else '低',
            ('把覆盖率 <0.7 的标的排除出推荐池' if cov['spread'] > 0
             else '覆盖率不影响收益，不必为它牺牲覆盖面'))

    # 4) 持有天数 —— ⚠ 这里最大的坑：持有天数 ≡ 推荐日早晚，两者被批次行情耦合。
    #    老批次持有久、又赶上 6-7 月大涨，看起来"持有越久赚越多"，
    #    那是**批次效应**，不是持有策略有效。这条教训必须点破，不能写成"该持有 77 天"。
    hc = [x for x in (S.get('hold_curve') or []) if x[1] >= 20]
    if len(hc) >= 3:
        best = max(hc, key=lambda x: x[3])
        worst = min(hc, key=lambda x: x[3])
        add('L-HOLD', 'timing',
            '持有 %d 天的批次均值 %+.2f%%（n=%d），持有 %d 天仅 %+.2f%%（n=%d）；'
            '但持有天数 = 推荐日早晚，与批次行情耦合，不能读成"持有越久越好"'
            % (best[0], best[3], best[1], worst[0], worst[3], worst[1]),
            '中', '跨批次比收益必须先固定推荐日；复盘只在同批次内横向比')

    # 5) 价位 —— 同样要求批次内一致才算数
    pb = S.get('price_bands') or {}
    if len(pb) >= 2:
        bs = sorted(pb.items(), key=lambda kv: -kv[1]['avg'])
        hi, lo = bs[0], bs[-1]
        if hi[1]['avg'] - lo[1]['avg'] >= 20 and hi[1]['n'] >= 20 and lo[1]['n'] >= 20:
            ch = S.get('cohort') or []
            months = ['%s %s %.0f%%' % (c['m'][2:], k, v['wr'])
                      for c in ch for k, v in c['bands'].items() if k == hi[0]]
            same = bool(ch) and all(
                (c['bands'].get(hi[0], {}).get('wr', 0) >= max(
                    [v['wr'] for k, v in c['bands'].items() if k != hi[0]] or [0]))
                for c in ch if c['bands'].get(hi[0]))
            add('L-PRICE', 'market',
                '¥%s 区间均值 %+.2f%%（n=%d），¥%s 区间仅 %+.2f%%（n=%d）%s'
                % (hi[0], hi[1]['avg'], hi[1]['n'], lo[0], lo[1]['avg'], lo[1]['n'],
                   '（同批次内一致：%s）' % '、'.join(months) if same else ''),
                '中', '推荐池向 ¥%s 区间倾斜' % hi[0] if same else '先观察，批次内不一致')

    # 5.5) 数据缺口 —— 这直接决定了上面哪些结论能信
    if S.get('factor_cov') is not None and S['factor_cov'] < 50:
        add('L-GAP', 'source',
            '全库 %d 条推荐里只有 %d 条（%.1f%%）带维度数据（dims 自 2026-09-18 才写入），'
            '因子分层实际样本 n=%d、中位持有 %s 天'
            % (S.get('n_all', 0), S.get('factor_n', 0), S['factor_cov'],
               S.get('factor_n', 0), S.get('factor_held', '?')),
            '高', '因子类结论一律标注"样本不足"；维度数据攒到 200 条以上再据此改权重')

    # 6) 门槛回测里最强的两条（一正一负）
    rules = S.get('rules') or []
    if rules:
        good = [r for r in rules if r['vs'] > 5 and r['n'] >= 30]
        bad = [r for r in rules if r['vs'] < -5 and r['n'] >= 30]
        if good:
            g = good[0]
            add('L-RULE+', 'scoring',
                '门槛「%s」：n=%d 胜率 %.1f%% 均值 %+.2f%%，比基准组高 %.2f 个百分点'
                % (g['rule'], g['n'], g['wr'], g['avg'], g['vs']),
                '高', '把该条件写进推荐门槛（硬条件或加分项）')
        if bad:
            bd = bad[0]
            add('L-RULE-', 'scoring',
                '门槛「%s」：n=%d 胜率 %.1f%% 均值 %+.2f%%，比基准组低 %.2f 个百分点'
                % (bd['rule'], bd['n'], bd['wr'], bd['avg'], abs(bd['vs'])),
                '高', '把该条件改成减分项或直接排除')

    # 7) 大盘基准（这是"胜率看着低"的关键背景）
    if S.get('mkt_med') is not None:
        add('L-MKT', 'market',
            '全市场 %d 件区间中位涨幅 %+.2f%%，推荐跑赢大盘比例 %.1f%%'
            % (S.get('mkt_n', 0), S['mkt_med'], S.get('beat', 0)),
            '高', '评价推荐必须用"跑赢大盘"，不能只看"涨了没有"')
    return L[:6]



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
    
    # ★ 2026-09-25 重写：先算统计，再交给 AI 解读。
    #   原实现只喂「最近 40 条 + 各自理由」，AI 看不到任何统计量，
    #   只能把推荐理由里的字眼复读一遍（"多平台溢价/流动性"），产出空话。
    ps = _load_json(os.path.join(DATA_DIR, 'price_summary.json')) or {}
    window_days = 9
    try:
        _cfg = _load_json(os.path.join(DATA_DIR, 'data_status.json')) or {}
        _w = _cfg.get('score_window_days')
        if isinstance(_w, (int, float)) and _w > 0:
            window_days = int(_w)
    except Exception:
        pass
    S = _compute_stats(tracks, ps, window_days)
    stats_text = _fmt_stats(S) if S else '（统计不可用，仅有原始清单）'

    market_bg = _get_market_background()

    print('[TRACK-AI] 开始 %d 条追踪分析（基准组 %d 条）…' % (total, S["n_base"] if S else 0))
    t0 = time.time()
    nS = S or {}

    # ── 事实层：全部由 Python 生成，AI 挂了也有完整分析 ──
    verdicts = _auto_verdicts(nS)
    lessons = _auto_lessons(nS)
    # 推荐理由关键词：有效因子 = 该强调，无效/反向因子 = 该回避
    _use = [v['f'] for v in verdicts if v['v'] in ('有效', '偏弱')][:3]
    _avoid = [v['f'] for v in verdicts if v['v'] in ('无效', '反向')][:3]

    # ── ① 总览（AI 唯一一次 JSON，字段短、给真实示例，避免它把说明当值）──
    p1 = ('下面是**已经算好**的推荐战绩统计，你只做解读，不要重算、不要编数字。\n\n'
          '%s\n\n【市场背景】%s\n\n'
          '返回JSON，四个字段都按示例的写法填（示例只是格式示范，内容必须换成上面的真实数字）：\n'
          '{"verdict":"跑赢大盘83.9%%，但ECO通道胜率仅21.1%%",'
          '"success_pattern":"BUFF通道n=917胜率74.6%%，均值+69.98%%",'
          '"failure_pattern":"ECO通道n=109胜率21.1%%，均值-18.18%%",'
          '"confidence_trend":"下降",'
          '"market_signal":"大盘中位-13.42%%，推荐抗跌"}\n'
          '注意：confidence_trend 只能是 上升/下降/持平 三个词之一；verdict 不超过 25 字。'
          % (stats_text, market_bg))
    ov = _ai_json(p1, max_tokens=400) or {}
    _trend = str(ov.get('confidence_trend') or '')
    if _trend not in ('上升', '下降', '持平'):
        _trend = '持平'

    # ── ② 因子动作：纯文本，不给 JSON 占位符（flash 会把占位符原样吐回来）──
    if verdicts:
        fac_lines = '\n'.join(
            '%s：%s（%s）' % (v['f'], v['v'], v['evidence']) for v in verdicts)
        p2 = ('下面是因子分层检验结果，判定已由规则给出（区分度=高档均值−低档均值）。\n'
              '%s\n\n'
              '请给每个因子配一句**具体可执行**的动作，15 字内，'
              '必须落到"权重调到多少"或"写进/排除哪个门槛"，不要复述判定、不要写空话。\n'
              '输出格式：每行一条，用竖线分隔，不要序号、不要JSON、不要多余文字：\n'
              '因子名|动作\n例如：\nBUFF维度分|权重由0.30提到0.35'
              % fac_lines)
        txt2 = _ai_text(p2, max_tokens=400)
        acts = _parse_pipe(txt2, 2)
        for v in verdicts:
            a = acts.get(v['f']) or ['']
            v['action'] = a[0] if isinstance(a, list) else str(a)

    # ── ③ 权重建议（页面要解析开头的数字，所以必须 +N% / -N% 开头）──
    tg_txt = ('；'.join('%s 胜率%.1f%% 均值%+.2f%%' % (k, v['wr'], v['avg'])
                        for k, v in nS.get('tags', {}).items()) or '（无）')
    beat_txt = ('大盘中位 %+.2f%%，推荐跑赢大盘 %.1f%%' % (nS['mkt_med'], nS.get('beat', 0))
                if nS.get('mkt_med') is not None else '（无大盘基准）')
    cov_txt = next((v['evidence'] for v in verdicts if v['f'] == '数据覆盖率'), '无')
    p3 = ('当前打分权重：ECO 0.40 / BUFF 0.30 / 流通(供给+求购) 0.15 / 悠悠YYYP 0.15。\n'
          '通道表现：%s\n大盘：%s\n数据覆盖率：%s\n因子判定：%s\n\n'
          '给四个维度各一个增量建议，**必须以 +N%% / -N%% / 不变 开头**（页面要解析这个数字），'
          '单次不超过 ±5%%，后面用斜杠分隔再写一句 20 字内的依据（引用上面的数字）。\n'
          '另外两句：premium = 溢价率阈值该怎么设（引用门槛回测数字）；'
          'liquidity = 流动性/覆盖率门槛该怎么设。\n'
          '返回JSON：{"eco":"-5%%/ECO通道胜率21.1%%","buff":"+5%%/BUFF通道胜率74.6%%",'
          '"flow":"不变/区分度不足3%%","yy":"+2%%/悠悠溢价门槛有效",'
          '"premium":"只推BUFF溢价<0的，n=52但均值-1.96%%，暂不加",'
          '"liquidity":"覆盖率<0.7的排除，占比n见统计"}'
          % (tg_txt, beat_txt, cov_txt,
             '；'.join('%s=%s' % (v['f'], v['v']) for v in verdicts[:5]) or '（无）'))
    sf_raw = _ai_json(p3, max_tokens=400) or {}

    # ── ④ 门槛：数字已算好，AI 只判断采用与否（纯文本）──
    what_if = []
    rules = nS.get('rules') or []
    if rules:
        rule_lines = '\n'.join('%s：n=%d 胜率%.1f%% 均值%+.2f%% ｜ vs基准 %+.2f%%'
                               % (r['rule'], r['n'], r['wr'], r['avg'], r['vs']) for r in rules[:8])
        p4 = ('下面是用真实数据回测出的候选推荐门槛（子集来自基准组 %d 条，基准组均值 %s%%）。\n'
              '%s\n\n'
              '逐条判断值不值得写进推荐门槛。vs基准为正 = 该子集比全组好。\n'
              '输出格式：每行一条，竖线分隔，不要序号、不要JSON：\n'
              '规则名|采用或观察或不采用|理由（20字内，必须带数字）'
              % (nS.get('n_base', 0), nS.get('base_avg', 0), rule_lines))
        acts4 = _parse_pipe(_ai_text(p4, max_tokens=500), 3)
        for r in rules[:8]:
            a = acts4.get(r['rule'])
            if a and len(a) >= 2:
                adopt, note = a[0], a[1]
            else:
                # AI 常常只挑它认为重要的几条回答，其余略过。
                # 这里按 vs基准 的符号给规则化默认（比无意义的"观察"有用），并标记为自动判定。
                adopt = '采用' if r['vs'] > 5 else ('不采用' if r['vs'] < -5 else '观察')
                note = ''
            what_if.append({'rule': r['rule'], 'n': r['n'], 'wr': r['wr'], 'avg': r['avg'],
                            'vs_base': r['vs'], 'adopt': adopt, 'note': note,
                            'auto': not bool(a)})

    # ── ⑤ 只问一句话：推荐理由文案怎么改（纯文本）──
    p5 = ('已证实有效的维度：%s\n已证实无效/反向的维度：%s\n基准组胜率 %s%% 均值 %s%%\n\n'
          '请给 80 字以内的"推荐理由生成优化建议"：明确应该写进理由的数字、'
          '应该删掉的套话。只输出建议正文，不要引号、不要前缀、不要JSON。'
          % ('、'.join(_use) or '（无）', '、'.join(_avoid) or '（无）',
             nS.get('base_wr', 0), nS.get('base_avg', 0)))
    tweak = (_ai_text(p5, max_tokens=300) or '').strip().strip('"').strip()

    print('[TRACK-AI] 完成：总览%s 因子%d 门槛%d 教训%d（%.0fs）'
          % ('OK' if ov.get('verdict') else 'FAIL', len(verdicts),
             len(what_if), len(lessons), time.time() - t0))

    analysis = {
        'overview': {
            'verdict': ov.get('verdict') or '',
            'success_pattern': ov.get('success_pattern') or '',
            'failure_pattern': ov.get('failure_pattern') or '',
            'confidence_trend': _trend,
            'market_signal': ov.get('market_signal') or '',
        },
        'factor_verdicts': verdicts,
        'what_if': what_if,
        'reason_analysis': {
            'right_reasons': ov.get('success_pattern') or '',
            'wrong_reasons': ov.get('failure_pattern') or '',
            'reason_keywords_use': '、'.join(_use),
            'reason_keywords_avoid': '、'.join(_avoid),
        },
        'lessons': lessons,
        'scoring_feedback': {
            'eco_weight_advice': sf_raw.get('eco') or '不变',
            'buff_weight_advice': sf_raw.get('buff') or '不变',
            'flow_weight_advice': sf_raw.get('flow') or '不变',
            'yy_weight_advice': sf_raw.get('yy') or '不变',
            'premium_threshold_advice': sf_raw.get('premium') or '',
            'liquidity_advice': sf_raw.get('liquidity') or '',
        },
        'reason_prompt_tweak': tweak,
        'recommendation_prompt_tweak': tweak,
    }
    analysis['meta'] = {
        'total_tracks': total,
        'date_range': f"{dates[0]}~{dates[-1]}" if dates else 'N/A',
        'analyzed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'model': _ai_model_label(),
        'rounds': 5,
        'ai_note': '因子判定/教训/门槛数字均由统计引擎算出（auto=True），AI 只补动作与文案建议',
        # ★ 保留喂进去的统计原值：页面可直接展示"数据说了什么"，
        #   不依赖 AI 转述（AI 负责解读，数字由我们自己算）
        'stats': S,
    }
    return analysis


def _get_market_background():
    """获取当前市场背景数据（含大盘涨跌，供 AI 对比推荐是否跑赢）"""
    bg_parts = []

    # 从 market_overview.json 获取大盘（★ 2026-09-25 新增：原来完全没喂大盘，
    #    AI 只能看到"推荐跌了"，不知道**全市场都在跌**，必然给出"要保守"的空话）
    ov = _load_json(os.path.join(DATA_DIR, 'market_overview.json'))
    if ov:
        idx = ov.get('index') or {}
        ud = ov.get('updown') or {}
        tr = ov.get('trade') or {}
        gd = ov.get('greedy') or {}
        if idx:
            bg_parts.append(f"饰品指数 {idx.get('current','?')}（{idx.get('change_pct',0):+.2f}%）")
        if ud:
            bg_parts.append(f"全市场涨{ud.get('up','?')}/平{ud.get('flat','?')}/跌{ud.get('down','?')}")
        if tr:
            bg_parts.append(f"成交额 {tr.get('amount_mom',0):+.1f}%")
        if gd:
            bg_parts.append(f"情绪 {gd.get('label','?')}({gd.get('value','?')})")

    # 从 price_summary 算全池区间中位涨幅 —— AI 判断"跑赢/跑输"的唯一基准
    ps = _load_json(os.path.join(DATA_DIR, 'price_summary.json')) or {}
    pool = []
    for _k, _d in ps.items():
        if not isinstance(_d, dict):
            continue
        _pr = _d.get('prices') or []
        if len(_pr) >= 2 and _pr[0]:
            try:
                pool.append((float(_pr[-1]) - float(_pr[0])) / float(_pr[0]) * 100)
            except Exception:
                pass
    if len(pool) >= 50:
        pool.sort()
        med = pool[len(pool) // 2]
        bg_parts.append(f"★大盘基准：全市场{len(pool)}件区间中位涨幅 {med:+.1f}%"
                        f"（中位持有天数与推荐样本相当），推荐**跑赢大盘才算赢**")

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


# ══════════════ 统计引擎（2026-09-25 新增）══════════════
# 背景：原 prompt 只喂「最近 40 条 + 自己的理由」，AI 看不到任何统计量 →
# 只能复读推荐理由本身的字眼（"多平台溢价/流动性"），产出空话。
# 下面这组函数把库里的真实数据先算成结论，再交给 AI 解读。

_WIN_LOOKBACK_DAYS = 9   # 涨幅「已定型」的最小持有天数
_LOOKBACK_SLACK = 3      # 允许比 window 少几天（样本更全）


def _latest_price(ps, it):
    """取该饰品最新价：先英文名（hash_name），再中文名"""
    for k in (it.get('hash_name'), it.get('name')):
        if not k:
            continue
        d = ps.get(k)
        if isinstance(d, dict):
            pr = d.get('prices') or []
            if pr and pr[-1]:
                try:
                    return float(pr[-1])
                except Exception:
                    pass
    return 0.0


def _build_row(dt, it, ps, today):
    """把一条推荐记录变成带收益/持有天数/dims 的分析行"""
    p = float(it.get('price') or 0)
    c = _latest_price(ps, it)
    if p <= 0 or c <= 0:
        return None
    try:
        d0 = time.strptime(dt, '%Y-%m-%d')
        held = int((time.mktime(today) - time.mktime(d0)) / 86400)
    except Exception:
        held = 0
    return {'date': dt, 'name': it.get('name', ''), 'rec': p, 'cur': c,
            'chg': (c - p) / p * 100, 'held': held,
            'tag': it.get('tag'), 'score': it.get('score'),
            'label': it.get('tag_label', ''), 'dims': it.get('dims') or {},
            'reason': it.get('reason', '') or ''}


def _compute_stats(tracks, ps, window_days):
    """全套统计：基准窗口/近期批次/因子分层/持有天数曲线/tag 与价位分组"""
    today = time.localtime()
    # tracks 是 load_all_tracks() 展平后的列表（每项含 'date'，不是 (date, item) 元组）
    rows = [r for r in (_build_row(t.get('date', ''), t, ps, today) for t in tracks) if r]
    if not rows:
        return None
    S = {'n_all': len(rows), 'window': window_days}

    # ── 基准组：持有天数达标（涨幅已定型）──
    base = [r for r in rows if r['held'] >= window_days - _LOOKBACK_SLACK]
    if len(base) < 20:
        base = rows
    S['n_base'] = len(base)
    S['base_wr'] = round(sum(1 for r in base if r['chg'] > 0) / len(base) * 100, 1)
    S['base_avg'] = round(sum(r['chg'] for r in base) / len(base), 2)
    S['base_med'] = round(sorted(r['chg'] for r in base)[len(base) // 2], 2)

    # ── 近期批次（窗口未走完，单独列，避免与基准组混淆）──
    rec = [r for r in rows if r['held'] < window_days - _LOOKBACK_SLACK]
    if rec:
        S['n_recent'] = len(rec)
        S['recent_wr'] = round(sum(1 for r in rec if r['chg'] > 0) / len(rec) * 100, 1)
        S['recent_avg'] = round(sum(r['chg'] for r in rec) / len(rec), 2)
        S['recent_days'] = sorted(set(r['held'] for r in rec))

    # ── 大盘基准 ──
    pool = []
    for _k, _d in ps.items():
        if not isinstance(_d, dict):
            continue
        _pr = _d.get('prices') or []
        if len(_pr) >= 2 and _pr[0]:
            try:
                pool.append((float(_pr[-1]) - float(_pr[0])) / float(_pr[0]) * 100)
            except Exception:
                pass
    if len(pool) >= 50:
        pool.sort()
        med = pool[len(pool) // 2]
        S['mkt_med'] = round(med, 2)
        S['mkt_n'] = len(pool)
        S['beat'] = round(sum(1 for r in base if r['chg'] > med) / len(base) * 100, 1)

    # ── 因子分层：每个维度分三档看收益差（这才是"分析"而非"复读"）──
    FACTORS = [
        ('eco_score', 'ECO维度分'), ('buff_score', 'BUFF维度分'),
        ('n_cov', '数据覆盖率'), ('n_dev_steam', '相对Steam偏离'),
        ('n_premium_buff', 'BUFF溢价'), ('n_premium_yyyp', '悠悠溢价'),
        ('n_supply', '在售件数'), ('n_supply_real', '真实存世量'),
        ('supply_chg7', '7日供给变化'), ('buff_buy_num', 'BUFF求购单'),
        ('buff_sell_num', 'BUFF在售单'), ('yyyp_sell_num', '悠悠在售件'),
        ('eco_qg_total', 'ECO求购单'),
    ]
    S['factors'] = []
    for key, label in FACTORS:
        pairs = [(r['dims'].get(key), r['chg']) for r in base
                 if isinstance(r['dims'].get(key), (int, float))]
        if len(pairs) < 30:
            continue
        pairs.sort(key=lambda x: x[0])
        n = len(pairs) // 3
        if n < 8:
            continue
        g = (pairs[:n], pairs[n:2 * n], pairs[2 * n:])
        m = lambda gg: sum(x[1] for x in gg) / len(gg)
        wr = lambda gg: sum(1 for x in gg if x[1] > 0) / len(gg) * 100
        S['factors'].append({
            'k': label, 'n': len(pairs),
            'lo': round(m(g[0]), 2), 'mid': round(m(g[1]), 2), 'hi': round(m(g[2]), 2),
            'wr_lo': round(wr(g[0]), 1), 'wr_hi': round(wr(g[2]), 1),
            'spread': round(m(g[2]) - m(g[0]), 2),
            'lo_rng': [round(g[0][0][0], 3), round(g[0][-1][0], 3)],
            'hi_rng': [round(g[2][0][0], 3), round(g[2][-1][0], 3)],
        })
    S['factors'].sort(key=lambda x: -abs(x['spread']))

    # ── 因子样本自检 ★ 2026-09-25 ──
    #   实测：rec_tracks.json 的 dims 是 09-18 才加的，1093 条里只有 120 条有。
    #   不标注的话，60 条样本的结论会被当成 1026 条的结论 —— 典型以偏概全。
    _fr = [r for r in rows if r['dims']]
    S['factor_n'] = len(_fr)
    S['factor_cov'] = round(len(_fr) / len(rows) * 100, 1)
    if _fr:
        _hs = sorted(r['held'] for r in _fr)
        S['factor_held'] = _hs[len(_hs) // 2]

    # ── 同批次（推荐月）内对比：排除"批次行情"混杂 ──
    #   总体对比会被批次污染（例：6 月批次整体涨 85%，9 月只涨 46%，
    #   若某通道恰好集中在 6 月，就会假性"表现好"）。只在批次内部比才可信。
    import collections as _co
    _byM = _co.defaultdict(list)
    for r in rows:
        _byM[r['date'][:7]].append(r)
    S['cohort'] = []
    for m in sorted(_byM):
        v = _byM[m]
        if len(v) < 30:
            continue
        e = {'m': m, 'n': len(v), 'tags': {}, 'bands': {}}
        # 标签必须与 price_bands 完全一致，否则同批次证据匹配不上（会显示成空）
        _bandk = lambda r: ('0~10' if r['rec'] < 10 else '10~50' if r['rec'] < 50
                            else '50~200' if r['rec'] < 200 else '200+')
        for _kf, _box in ((lambda r: r['tag'] or '?', e['tags']), (_bandk, e['bands'])):
            _sub = _co.defaultdict(list)
            for r in v:
                _sub[_kf(r)].append(r['chg'])
            for k, ch in _sub.items():
                if len(ch) >= 8:
                    _box[k] = {'n': len(ch),
                               'wr': round(sum(1 for x in ch if x > 0) / len(ch) * 100, 1),
                               'avg': round(sum(ch) / len(ch), 2)}
        S['cohort'].append(e)

    # ── 持有天数曲线（看"多少天见顶"）──
    byd = {}
    for r in rows:
        byd.setdefault(r['held'], []).append(r['chg'])
    S['hold_curve'] = [(k, len(v), round(sum(1 for x in v if x > 0) / len(v) * 100, 1),
                        round(sum(v) / len(v), 2))
                       for k, v in sorted(byd.items()) if len(v) >= 20]

    # ── tag / 价位分组 ──
    grp = {}
    for tg in ('eco', 'buff'):
        v = [r['chg'] for r in base if r['tag'] == tg]
        if len(v) >= 10:
            grp[tg] = {'n': len(v), 'wr': round(sum(1 for x in v if x > 0) / len(v) * 100, 1),
                       'avg': round(sum(v) / len(v), 2)}
    S['tags'] = grp

    S['price_bands'] = {}
    for lo, hi_ in ((0, 10), (10, 50), (50, 200), (200, 1e9)):
        v = [r['chg'] for r in base if lo <= r['rec'] < hi_]
        if len(v) >= 8:
            S['price_bands'][('%g~%g' % (lo, hi_) if hi_ < 1e9 else '%g+' % lo)] = {
                'n': len(v), 'wr': round(sum(1 for x in v if x > 0) / len(v) * 100, 1),
                'avg': round(sum(v) / len(v), 2)}

    # ── 候选门槛回测 ★ 2026-09-25 ──
    #   以前把"如果当初改了规则会怎样"交给 AI 答 → 它直接编 n/胜率/均值。
    #   现在**用真实数据把子集算出来**，AI 只负责判断"要不要写进门槛"。
    rules = []
    _ba = S['base_avg']

    def _add(name, pred):
        try:
            v = [r for r in base if pred(r)]
        except Exception:
            return
        if len(v) < 20:
            return
        wr = sum(1 for r in v if r['chg'] > 0) / len(v) * 100
        avg = sum(r['chg'] for r in v) / len(v)
        rules.append({'rule': name, 'n': len(v), 'wr': round(wr, 1),
                      'avg': round(avg, 2), 'vs': round(avg - _ba, 2)})

    _num = lambda r, k: (r['dims'].get(k) if isinstance(r['dims'].get(k), (int, float)) else None)
    _add('数据覆盖率 ≥ 0.9', lambda r: (_num(r, 'n_cov') or 0) >= 0.9)
    _add('数据覆盖率 < 0.7', lambda r: (_num(r, 'n_cov') is not None) and _num(r, 'n_cov') < 0.7)
    _add('相对Steam偏离 < -10%（比Steam便宜）', lambda r: (_num(r, 'n_dev_steam') is not None) and _num(r, 'n_dev_steam') < -10)
    _add('相对Steam偏离 > +10%（比Steam贵）', lambda r: (_num(r, 'n_dev_steam') is not None) and _num(r, 'n_dev_steam') > 10)
    _add('BUFF溢价 < 0（低于BUFF）', lambda r: (_num(r, 'n_premium_buff') is not None) and _num(r, 'n_premium_buff') < 0)
    _add('BUFF溢价 > 5%', lambda r: (_num(r, 'n_premium_buff') is not None) and _num(r, 'n_premium_buff') > 5)
    _add('悠悠溢价 < 0', lambda r: (_num(r, 'n_premium_yyyp') is not None) and _num(r, 'n_premium_yyyp') < 0)
    _add('真实存世量 ≤ 300', lambda r: (_num(r, 'n_supply_real') or 0) > 0 and _num(r, 'n_supply_real') <= 300)
    _add('真实存世量 > 3000', lambda r: (_num(r, 'n_supply_real') or 0) > 3000)
    _add('BUFF求购单 ≥ 20', lambda r: (r['dims'].get('buff_buy_num') or 0) >= 20)
    _add('通道 = BUFF', lambda r: r['tag'] == 'buff')
    _add('通道 = ECO', lambda r: r['tag'] == 'eco')
    _add('推荐价 < ¥10', lambda r: r['rec'] < 10)
    _add('推荐价 ≥ ¥200', lambda r: r['rec'] >= 200)
    S['rules'] = sorted(rules, key=lambda x: -abs(x['vs']))

    # ── 最好/最差样本（给 AI 做归因）──
    srt = sorted(base, key=lambda r: -r['chg'])
    def brief(r):
        d = r['dims']
        return ('%s ¥%.0f→¥%.0f (%+.0f%%, 持%dd) 分%.0f [ECO%.0f/BUFF%.0f 覆盖%.2f '
                'Steam偏离%s 溢价%s 在售%s 存世%s]'
                % (r['name'][:26], r['rec'], r['cur'], r['chg'], r['held'], r['score'] or 0,
                   d.get('eco_score') or 0, d.get('buff_score') or 0, d.get('n_cov') or 0,
                   ('%+.1f' % d['n_dev_steam']) if isinstance(d.get('n_dev_steam'), (int, float)) else '—',
                   ('%+.1f' % d['n_premium_buff']) if isinstance(d.get('n_premium_buff'), (int, float)) else '—',
                   d.get('n_supply'), d.get('n_supply_real')))
    S['top'] = [brief(r) for r in srt[:10]]
    S['bottom'] = [brief(r) for r in srt[-10:]]
    return S


def _fmt_stats(S):
    """把统计结果压成紧凑文本（喂给 AI）"""
    L = []
    L.append('【统计口径】"基准组"= 持有≥%d 天的推荐（涨幅已定型）；"近期批次"= 持有不足，涨幅未走完，不可与之比较。'
             % (S['window'] - _LOOKBACK_SLACK))
    L.append('基准组 %d 条：涨了就算赢 %.1f%%｜平均 %+.2f%%｜中位 %+.2f%%'
             % (S['n_base'], S['base_wr'], S['base_avg'], S['base_med']))
    if S.get('mkt_med') is not None:
        L.append('★大盘基准（全市场 %d 件区间中位涨幅）：%+.2f%% → 推荐跑赢大盘比例 **%.1f%%**'
                 % (S['mkt_n'], S['mkt_med'], S.get('beat', 0)))
    if S.get('n_recent'):
        L.append('近期批次 %d 条（持有 %s 天）：胜率 %.1f%%｜平均 %+.2f%% ← 窗口未走完，仅供参考'
                 % (S['n_recent'], '%d~%d' % (min(S['recent_days']), max(S['recent_days'])),
                    S['recent_wr'], S['recent_avg']))

    L.append('\n【因子分层检验】把基准组按各维度分三档，看高档 vs 低档的收益差（区分度=高组−低组）')
    if S.get('factor_n'):
        L.append('  ⚠ 样本提示：全库仅 %d/%d 条（%.1f%%）带维度数据（dims 自 2026-09-18 才写入），'
                 '本表实际样本 n=%d、中位持有 %s 天 → **结论强度有限，只可作为方向性参考**'
                 % (S['factor_n'], S['n_all'], S.get('factor_cov', 0),
                    S['factor_n'], S.get('factor_held', '?')))
    for f in S['factors'][:10]:
        L.append('  %s：低档(%.3f~%.3f) %+.2f%% 胜%.0f%% ｜ 高档(%.3f~%.3f) %+.2f%% 胜%.0f%% ｜ **区分度 %+.2f%%** (n=%d)'
                 % (f['k'], f['lo_rng'][0], f['lo_rng'][1], f['lo'], f['wr_lo'],
                    f['hi_rng'][0], f['hi_rng'][1], f['hi'], f['wr_hi'], f['spread'], f['n']))
    L.append('  ※ 区分度接近 0 或为负 = 该维度**没有预测力**，权重应下调')

    L.append('\n【持有天数 → 收益】')
    for k, n, wr, avg in S['hold_curve']:
        L.append('  持有 %3d 天：n=%d 胜率 %.1f%% 均值 %+.2f%%' % (k, n, wr, avg))

    if S['tags']:
        L.append('\n【ECO/BUFF 通道对比（总体，含批次混杂）】')
        for tg, v in S['tags'].items():
            L.append('  %s：n=%d 胜率 %.1f%% 均值 %+.2f%%' % (tg, v['n'], v['wr'], v['avg']))
    if S.get('cohort'):
        L.append('\n【同批次内对比 ★抗混杂】只在同一个推荐月内部比，排除"某批次整体行情好"的干扰。'
                 '只有**每个月都同向**的差异，才算是真信号')
        for e in S['cohort']:
            _t = '；'.join('%s n=%d 胜%.0f%% 均%+.1f%%' % (k, v['n'], v['wr'], v['avg'])
                          for k, v in sorted(e['tags'].items()))
            _b = '；'.join('%s n=%d 胜%.0f%% 均%+.1f%%' % (k, v['n'], v['wr'], v['avg'])
                          for k, v in sorted(e['bands'].items()))
            L.append('  %s（总%d）通道：%s' % (e['m'], e['n'], _t or '—'))
            L.append('  %s（总%d）价位：%s' % (' ' * len(e['m']), e['n'], _b or '—'))
    if S['price_bands']:
        L.append('\n【价位分组】')
        for b, v in S['price_bands'].items():
            L.append('  ¥%s：n=%d 胜率 %.1f%% 均值 %+.2f%%' % (b, v['n'], v['wr'], v['avg']))

    if S.get('rules'):
        L.append('\n【候选门槛回测】在基准组内筛子集（数字已算好，不要重算）：vs基准 = 子集均值 − 基准组均值(%.2f%%)'
                 % S['base_avg'])
        for r in S['rules'][:12]:
            L.append('  %s：n=%d 胜率 %.1f%% 均值 %+.2f%% ｜ **vs基准 %+.2f%%**'
                     % (r['rule'], r['n'], r['wr'], r['avg'], r['vs']))

    L.append('\n【基准组表现最好的 10 件】（用于找"赢家共性"）')
    L.extend('  ' + x for x in S['top'])
    L.append('\n【基准组表现最差的 10 件】（用于找"输家共性"）')
    L.extend('  ' + x for x in S['bottom'])
    return '\n'.join(L)

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
        'reason_analysis': analysis.get('reason_analysis', {}),
        'prompt_tweak': analysis.get('reason_prompt_tweak', '') or analysis.get('recommendation_prompt_tweak', ''),
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
    """获取当前教训，格式化为可注入推荐Prompt的文本（含推荐理由反馈）"""
    lessons_db = _load_json(LESSONS_PATH)
    if not lessons_db:
        return ''
    
    lines = []
    
    # 推荐理由优化（从 reason_analysis 提取）
    ah = lessons_db.get('analysis_history', [])
    if ah:
        latest = ah[-1]
        ra = latest.get('reason_analysis', {})
        if ra.get('right_reasons') or ra.get('wrong_reasons'):
            lines.append('\n【推荐理由优化反馈（AI追踪分析）】')
            if ra.get('right_reasons'):
                lines.append(f'- ✅ 正确理由特征: {ra["right_reasons"]}')
            if ra.get('wrong_reasons'):
                lines.append(f'- ❌ 错误理由特征: {ra["wrong_reasons"]}')
            if ra.get('reason_keywords_use'):
                lines.append(f'- 📝 推荐理由中应强调: {ra["reason_keywords_use"]}')
            if ra.get('reason_keywords_avoid'):
                lines.append(f'- 🚫 推荐理由中应避免: {ra["reason_keywords_avoid"]}')
    
    # 评分教训
    lessons = lessons_db.get('lessons', [])
    if lessons:
        if not lines:
            lines.append('\n【历史追踪教训（来自AI分析）】')
        else:
            lines.append('\n【评分权重教训】')
        for l in lessons[:3]:
            conf = l.get('confirmed', 1)
            stars = '⭐' * min(conf, 3)
            lines.append(f"- {stars} [{l.get('category','')}] {l.get('lesson','')} → {l.get('action','')}")
    
    return '\n'.join(lines) if lines else ''

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
    CI管线入口 — 预算充裕（月15元），允许更频繁分析
    规则：
      - 每天最多 4 次（每6小时）
      - track 增长 <10% 且 <6h 时跳过
    """
    if tracks is None:
        tracks = load_all_tracks()
    
    if not tracks or len(tracks) < 3:
        print(f'[TRACK-AI] Insufficient tracks ({len(tracks) if tracks else 0}), skip')
        return None
    
    # ── 频率控制 ──
    lessons_db = _load_json(LESSONS_PATH) or {}
    last_analysis_ts = lessons_db.get('last_updated', '')
    last_analysis_count = lessons_db.get('last_track_count', 0)
    today = time.strftime('%Y-%m-%d')
    
    # 距离上次 <4 小时 → 跳过
    if last_analysis_ts:
        try:
            last_dt = time.strptime(last_analysis_ts[:19], '%Y-%m-%dT%H:%M:%S')
            hours_ago = (time.time() - time.mktime(last_dt)) / 3600
            if hours_ago < 4:
                # 但如果 track 增长 >30%，破例分析
                growth = (len(tracks) - last_analysis_count) / max(last_analysis_count, 1) * 100
                if growth < 30:
                    print(f'[TRACK-AI] Last analysis {hours_ago:.1f}h ago (<4h) + growth {growth:.0f}%, skip')
                    return None
        except:
            pass
    
    # track 增长 <10% 且今天已分析过 → 跳过
    if last_analysis_ts.startswith(today) and last_analysis_count > 0:
        growth = (len(tracks) - last_analysis_count) / last_analysis_count * 100
        if growth < 10:
            print(f'[TRACK-AI] Today done + growth {growth:.0f}% (<10%), skip')
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
