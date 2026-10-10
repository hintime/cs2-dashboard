#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kronos 预测归档 —— 为命中率记分卡攒历史。

为什么必须有：
  update.py 每 6h 跑一次 Kronos 推理并**直接覆盖** ai_forecast.json，从不留档。
  没有历史预测 → 永远无法回答"Kronos 到底准不准"，预测板块只能标"实验性"
  却拿不出任何量化依据。这是本项目「静默失败」思路的另一个面：缺可验证性。

做什么：
  读当前 ai_forecast.json → 抽每项的 (hash_name, 预测日, current, forecast,
  change_pct, 预测方向) → 追加进 forecast_archive.jsonl（一行一条，带 run_id）。
  已存在同一 (run_id, hash_name) 则跳过（幂等，重跑不会写重）。

用法（服务器 cron / 手工）：
    /usr/bin/python3 /home/ubuntu/cs2-run/tools/kronos_archive.py
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = "/home/ubuntu/cs2-run"
SRC = os.path.join(REPO, "ai_forecast.json")
OUT = os.path.join(REPO, "forecast_archive.jsonl")
# 只保留最近 N 天的归档，避免文件无限膨胀（每轮 38 件 × 4 轮/天 ≈ 152 行/天）
KEEP_DAYS = 120


def main():
    if not os.path.exists(SRC):
        print("[FC-Archive] 跳过：ai_forecast.json 不存在")
        return 0
    try:
        with open(SRC, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        print("[FC-Archive] 读取预测失败: %s" % e)
        return 1

    run_id = "%s#%d" % (d.get("date") or "?", int(time.time()))
    items = d.get("items") or []
    if not items:
        print("[FC-Archive] 跳过：items 为空")
        return 0

    # 已有 run_id 前缀的行（重跑幂等）
    seen = set()
    if os.path.exists(OUT):
        with open(OUT, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    o = json.loads(line)
                    seen.add((o.get("run_id"), o.get("hash_name")))
                except Exception:
                    continue

    added = 0
    lines = []
    for it in items:
        hn = it.get("hash_name") or it.get("name")
        if not hn:
            continue
        if (d.get("date"), hn) in seen:
            continue
        rec = {
            "run_id": run_id,
            "date": d.get("date"),          # 预测生成日（= 可验证的起点）
            "hash_name": hn,
            "name": it.get("name"),
            "source": it.get("source"),
            "days": d.get("days"),
            "current": it.get("current"),
            "forecast": it.get("forecast"),
            "change_pct": it.get("change_pct"),
            "series_tail": (it.get("series") or [])[-1:] or None,  # 留末点，便于对齐
        }
        lines.append(json.dumps(rec, ensure_ascii=False))
        added += 1

    if not lines:
        print("[FC-Archive] 无新增（已归档过）")
        return 0

    with open(OUT, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("[FC-Archive] 已归档 %d 条预测（run_id=%s）→ %s" % (added, run_id, OUT))

    # 裁剪：按 date 保留最近 KEEP_DAYS 天
    try:
        cutoff = time.time() - KEEP_DAYS * 86400
        kept, dropped = [], 0
        with open(OUT, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    o = json.loads(line)
                    # date 形如 '2026-10-10 19:49'，取日期部分比较
                    ds = (o.get("date") or "")[:10]
                    ts = time.mktime(time.strptime(ds, "%Y-%m-%d")) if ds else 0
                    if ts >= cutoff:
                        kept.append(line)
                    else:
                        dropped += 1
                except Exception:
                    dropped += 1
        if dropped:
            with open(OUT, "w", encoding="utf-8") as f:
                f.writelines(kept)
            print("[FC-Archive] 裁剪：保留 %d 行，丢弃过期 %d 行" % (len(kept), dropped))
    except Exception as e:
        print("[FC-Archive] 裁剪跳过（不影响归档）: %s" % e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
