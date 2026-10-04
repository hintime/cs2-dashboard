#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kronos 微调语料构建器（服务器端，从最新 price_history.db 生成 CSV 语料）。

数据口径（义轩硬要求，勿放宽）：
  - 只用【连续多日、无大缺口】的密集采样：ts >= DENSE_SINCE(2026-09-18)，1h 节奏；
  - 相邻点间隔 > GAP_SPLIT_HOURS(12h) 即切段，序列在断点处断开，不做插值/补点；
  - 只保留长度 >= WINDOW(=lookback336+predict48+1=385) 的连续段，短段直接丢；
  - 每段滑窗样本数 = 段长 - WINDOW + 1。

输出：data/buff_b1h/*.csv，格式同 smoke 语料
      timestamps,open,high,low,close,volume,amount   （价格同时填 OHLC，volume/amount=0）
用法：venv/bin/python tools/build_corpus.py [--out DIR] [--max-items N] [--channel buff]
"""
import argparse, os, sqlite3, sys, json, datetime as dt

DENSE_SINCE = '2026-09-18'
GAP_SPLIT_HOURS = 12
WINDOW = 385            # lookback 336 + predict 48 + 1，与 config_cs2_buff_1h.yaml 一致

def parse_ts(s):
    for f in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M'):
        try:
            return dt.datetime.strptime(s, f)
        except ValueError:
            pass
    return dt.datetime.strptime(s[:16], '%Y-%m-%dT%H:%M')

def sanitize(name, idx):
    keep = []
    for ch in name:
        keep.append(ch if (ch.isalnum() or ch in '-_') else '_')
    s = ''.join(keep).strip('_').lower()
    return '%04d_%s.csv' % (idx, s[:60] or ('item%d' % idx))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='price_history.db')
    ap.add_argument('--out', default='data/buff_b1h')
    ap.add_argument('--channel', default='buff')
    ap.add_argument('--max-items', type=int, default=2000)
    ap.add_argument('--target-samples', type=int, default=20000)
    a = ap.parse_args()

    if not os.path.exists(a.db):
        print('NO DB', a.db); sys.exit(1)
    os.makedirs(a.out, exist_ok=True)
    # 清掉旧 csv（保留 report）
    for f in os.listdir(a.out):
        if f.lower().endswith('.csv'):
            os.remove(os.path.join(a.out, f))

    conn = sqlite3.connect('file:%s?mode=ro' % a.db, uri=True)
    cur = conn.execute(
        "SELECT item_name, ts, price FROM prices "
        "WHERE channel=? AND ts>=? ORDER BY item_name, ts", (a.channel, DENSE_SINCE))

    gap = dt.timedelta(hours=GAP_SPLIT_HOURS)
    idx = 0            # 语料文件序号
    items_done = 0
    samples = 0
    segs_kept = 0
    max_seg = 0
    cur_name = None
    cur_pts = []       # [(ts, price)]
    report_items = []

    def flush_item(name, pts):
        """把一个标的所有 >=WINDOW 的连续段写成 csv。返回(写文件数, 样本数, 最长段)。"""
        nonlocal idx, segs_kept, samples, max_seg
        nf = ns = 0
        seg = []
        segs = []
        for t, p in pts:
            if seg and (t - seg[-1][0]) > gap:
                if len(seg) >= WINDOW:
                    segs.append(seg)
                seg = []
            seg.append((t, p))
        if len(seg) >= WINDOW:
            segs.append(seg)
        for sgm in segs:
            if items_done + idx // 1 >= a.max_items * 3:   # 粗略上限保护
                break
            fn = sanitize(name, idx)
            path = os.path.join(a.out, fn)
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write('timestamps,open,high,low,close,volume,amount\n')
                for t, p in sgm:
                    ts = t.strftime('%Y/%m/%d %H:%M')
                    v = '%.2f' % p
                    f.write('%s,%s,%s,%s,%s,0,0\n' % (ts, v, v, v, v))
            n = len(sgm)
            idx += 1
            nf += 1
            ns += n - WINDOW + 1
            segs_kept += 1
            max_seg = max(max_seg, n)
        return nf, ns

    def handle(name, pts):
        nonlocal items_done, samples
        if not pts or items_done >= a.max_items:
            return
        nf, ns = flush_item(name, pts)
        if nf:
            items_done += 1
            samples += ns
            report_items.append({'file_seq': idx, 'name': name[:40], 'segments': nf, 'samples': ns})

    for name, ts, price in cur:
        if price is None or price <= 0:
            continue
        try:
            t = parse_ts(ts)
        except Exception:
            continue
        if name != cur_name:
            if cur_name is not None:
                handle(cur_name, cur_pts)
            cur_name = name
            cur_pts = []
        cur_pts.append((t, float(price)))
    if cur_name is not None:
        handle(cur_name, cur_pts)
    conn.close()

    ok = samples >= a.target_samples
    rep = {
        'generated': dt.datetime.now().strftime('%Y-%m-%d %H:%M'),
        'db': os.path.abspath(a.db), 'channel': a.channel,
        'window': WINDOW, 'dense_since': DENSE_SINCE, 'gap_hours': GAP_SPLIT_HOURS,
        'items_kept': items_done, 'csv_files': idx, 'segments_kept': segs_kept,
        'est_samples': samples, 'max_seg': max_seg, 'target_samples': a.target_samples,
        'gate_ok': ok,
    }
    with open(os.path.join(a.out, 'corpus_report.json'), 'w', encoding='utf-8') as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print('=== 语料构建完成 ===')
    print('标的 %d / 段 %d / csv %d / 估算样本 %d / 最长段 %d'
          % (items_done, segs_kept, idx, samples, max_seg))
    print('目标样本 %d → %s' % (a.target_samples, 'OK 可训练' if ok else '未达'))
    print('输出目录:', a.out)

if __name__ == '__main__':
    main()
