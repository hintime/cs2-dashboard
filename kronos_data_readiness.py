# -*- coding: utf-8 -*-
"""Kronos 微调数据就绪度检查（只读 price_history.db，不改任何东西）。

★ 硬门槛（义轩 2026-09-18 明确要求，勿删）：微调训练必须用「连续多日、无大缺口」的
  规则采样序列，**禁止拿稀疏/断点数据直接训练**（"不要看到就用"）。
  Kronos 的 512 步上下文默认等间隔，序列里混入多日空洞会污染训练。
  故本脚本不只数点数，还测**连续性**：
  - 相邻采样间隔 > GAP_SPLIT_HOURS 视为断点，序列在此切段；
  - 只有长度 >= SEQ_MIN 的连续段才算一条合格训练序列；
  - 2026-09-18 之前的旧数据是每日 1 次稀疏采样（90 天仅 57 采样日），天然被切段淘汰，
    不进微调语料 —— 只继续用于零样本推理。

运行：python kronos_data_readiness.py
产物：readiness_report.json（可提交/复查）
"""
import sqlite3, os, json, statistics, datetime as dt

DB = os.environ.get('PRICE_HIST_DB') or r'E:\cs2-data\price_history.db'
CHANNELS = ('eco', 'buff', 'yy')
SEQ_MIN = 512            # 训练序列最小长度（Kronos 上下文 512 步）
GAP_SPLIT_HOURS = 12     # 相邻点间隔超过 12h 视为断点、切段
SEQ_GATE = 300           # 合格训练序列总数门槛（起步值，可调）
DENSE_SINCE = '2026-09-18'  # 3h 高频采集起始日（之前为每日级稀疏采样）
DENSE_SINCE_DT = dt.datetime.strptime(DENSE_SINCE, '%Y-%m-%d')

def parse_ts(s):
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M'):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return dt.datetime.strptime(s[:16], '%Y-%m-%dT%H:%M')

def analyze_channel(cur, ch):
    rows = cur.execute(
        "SELECT item_name, ts FROM prices WHERE channel=? ORDER BY item_name, ts", (ch,)
    ).fetchall()
    if not rows:
        return None
    per = {}
    dense_pts = 0
    tmin = tmax = None
    for name, ts in rows:
        per.setdefault(name, []).append(ts)
        if tmin is None or ts < tmin: tmin = ts
        if tmax is None or ts > tmax: tmax = ts
        if ts >= DENSE_SINCE:
            dense_pts += 1

    seg_counts = []        # 每标的最长连续段（点数）
    seq_total = 0          # 合格训练序列总数（>=SEQ_MIN 的连续段）
    seq_items = 0          # 拥有至少一条合格序列的标的数
    dense_items = 0        # 高频采集期(>=DENSE_SINCE)有点的标的数
    intervals_h = []       # 高频期相邻间隔（小时），估实际采集节奏
    for name, tss in per.items():
        tss.sort()
        if tss[-1] >= DENSE_SINCE:
            dense_items += 1
        # 连续切段
        best = 1
        cur_len = 1
        prev = parse_ts(tss[0])
        start = prev
        best_span_days = 0.0
        seq_here = 0
        for s in tss[1:]:
            t = parse_ts(s)
            gap_h = (t - prev).total_seconds() / 3600.0
            if t >= DENSE_SINCE_DT:
                intervals_h.append(gap_h)
            if gap_h > GAP_SPLIT_HOURS:
                if cur_len >= SEQ_MIN:
                    seq_total += 1; seq_here += 1
                    best_span_days = max(best_span_days, (prev - start).total_seconds() / 86400.0)
                best = max(best, cur_len)
                cur_len = 1
                start = t
            else:
                cur_len += 1
            prev = t
        if cur_len >= SEQ_MIN:
            seq_total += 1; seq_here += 1
            best_span_days = max(best_span_days, (prev - start).total_seconds() / 86400.0)
        best = max(best, cur_len)
        seg_counts.append(best)
        if seq_here:
            seq_items += 1

    seg_counts.sort()
    n = len(seg_counts)
    cad = statistics.median(intervals_h) if intervals_h else None
    return {
        'items': n,
        'points': len(rows),
        'dense_since_points': dense_pts,
        'dense_items': dense_items,
        'dense_cadence_h': round(cad, 2) if cad else None,
        'span': [tmin, tmax],
        'max_seg_points': {'p50': seg_counts[n // 2], 'p90': seg_counts[min(9 * n // 10, n - 1)], 'max': seg_counts[-1]},
        'finetunable_seqs': seq_total,
        'items_with_seq': seq_items,
    }

def main():
    if not os.path.exists(DB):
        print('NO DB:', DB); return
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    rep = {'generated': dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
           'db': DB,
           'thresholds': {'seq_min': SEQ_MIN, 'gap_split_hours': GAP_SPLIT_HOURS,
                          'seq_gate': SEQ_GATE, 'dense_since': DENSE_SINCE},
           'channels': {}}

    print('=== Kronos 微调数据就绪度（连续性门槛版） ===')
    print('门槛: 连续段 >=%d 点(切段阈值 %dh) | 序列总数 >= %d' % (SEQ_MIN, GAP_SPLIT_HOURS, SEQ_GATE))
    total_seqs = 0
    for ch in CHANNELS:
        r = analyze_channel(cur, ch)
        if not r:
            print('%-4s 无数据' % ch); continue
        rep['channels'][ch] = r
        total_seqs += r['finetunable_seqs']
        print('%-4s 标的 %5d | 点 %8d | 高频期点 %7d / 标的 %4d | 节奏 %s h' % (
            ch, r['items'], r['points'], r['dense_since_points'], r['dense_items'],
            r['dense_cadence_h']))
        print('     最长连续段 p50/p90/max: %d / %d / %d | 合格序列 %d 条 / %d 标的' % (
            r['max_seg_points']['p50'], r['max_seg_points']['p90'], r['max_seg_points']['max'],
            r['finetunable_seqs'], r['items_with_seq']))

    # 行情区间覆盖（周度中位数方向，全通道合并）
    rows = cur.execute("SELECT ts, price FROM prices ORDER BY ts").fetchall()
    weekly = {}
    for ts, price in rows:
        weekly.setdefault(parse_ts(ts).strftime('%Y-%W'), []).append(price)
    dirs = []
    prev = None
    for wk in sorted(weekly):
        m = statistics.median(weekly[wk])
        if prev is not None:
            dirs.append(1 if m > prev else -1)
        prev = m
    up, down = sum(1 for d in dirs if d > 0), sum(1 for d in dirs if d < 0)
    conn.close()

    gate_seq = total_seqs >= SEQ_GATE
    gate_regime = (up > 0 and down > 0)
    rep['regime'] = {'up_weeks': up, 'down_weeks': down, 'weeks': len(weekly)}
    rep['check'] = {'seq_total': total_seqs, 'gate_seq_ok': gate_seq, 'gate_regime_ok': gate_regime}
    rep['verdict'] = 'READY' if (gate_seq and gate_regime) else 'NOT_YET'

    print('--- 门槛 ---')
    print('合格训练序列 >= %d : %s (当前 %d 条)' % (SEQ_GATE, 'OK' if gate_seq else '未达', total_seqs))
    print('周度多空兼具      : %s (涨 %d / 跌 %d)' % ('OK' if gate_regime else '未达', up, down))
    print('=== 判定: %s ===' % rep['verdict'])
    print('注: 高频期(>= %s)若中间整机关机/睡眠，会在断点处切段 —— 序列只会变短，不会被污染。' % DENSE_SINCE)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'readiness_report.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print('报告已写:', out)

if __name__ == '__main__':
    main()
