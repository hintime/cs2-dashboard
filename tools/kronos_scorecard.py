#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kronos 预测命中率记分卡 —— 用归档预测 + 实际价格打分。

指标定义（都从forecast_archive.jsonl × price_history.db 算，不编造）：
  · 可验证样本= 已过了预测天数(days)、且实际价可查到的预测条数
  · 方向命中率  = sign(实际涨跌)== sign(预测涨跌) 的比例
  · 幅度误差    = |实际涨跌% - 预测涨跌%| 的均值（越低越好）
  · 方向偏差    = 实际涨跌 - 预测涨跌 的均值（>0 = 整体低估行情）

为什么需要：
  预测板块一直标「实验性/仅方向参考」，但没有任何量化依据。
  本脚本是唯一能回答「Kronos 到底准不准」的地方，也是后续决定
  要不要扩大预测覆盖面的唯一客观依据。

用法：
    /usr/bin/python3 /home/ubuntu/cs2-run/tools/kronos_scorecard.py
    /usr/bin/python3 ... --push     # 同时把结果 JSON 推上GitHub
    /usr/bin/python3 ... --notify   # 同时发企微
"""
import argparse
import json
import os
import sqlite3
import statistics
import sys
import time
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = "/home/ubuntu/cs2-run"
ARCHIVE = os.path.join(REPO, "forecast_archive.jsonl")
DB = os.path.join(REPO, "price_history.db")
OUT = os.path.join(REPO, "kronos_scorecard.json")
CHANNEL = "buff"


def load_archive():
    if not os.path.exists(ARCHIVE):
        return []
    out = []
    with open(ARCHIVE, "r", encoding="utf-8") as f:
        for line in f:
            try:
                o = json.loads(line)
                if o.get("date") and o.get("hash_name") and o.get("change_pct") is not None:
                    out.append(o)
            except Exception:
                continue
    return out


def parse_date(s):
    try:
        return datetime.strptime((s or "")[:10], "%Y-%m-%d")
    except Exception:
        return None


def actual_change_pct(conn, item_name, d0, d1):
    """从 price_history 取 d0 当日与 d1 当日的均价，算实际涨跌%。

    用日均价而非单点：一天内几十次采样，单点会被噪声主导。
    """
    cur = conn.execute(
        "SELECT substr(ts,1,10) d, AVG(price) FROM prices "
        "WHERE item_name=? AND channel=? AND substr(ts,1,10) IN (?,?) "
        "GROUP BY d", (item_name, CHANNEL, d0, d1))
    m = {r[0]: r[1] for r in cur}
    if d0 not in m or d1 not in m or not m[d0] or not m[d1]:
        return None
    return (m[d1] - m[d0]) / m[d0] * 100.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--notify", action="store_true")
    args = ap.parse_args()

    arch = load_archive()
    if not arch:
        msg = "无归档预测可评分（forecast_archive.jsonl 为空或不存在）"
        print("[FC-Score] " + msg)
        out = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
               "n_archive": 0, "n_verifiable": 0, "note": msg}
        _write(out)
        return 0

    if not os.path.exists(DB):
        print("[FC-Score] 跳过：price_history.db 不存在")
        return 1
    conn = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)

    today = datetime.now()
    rows = []
    n_pending = 0
    for a in arch:
        d0 = parse_date(a.get("date"))
        if not d0:
            continue
        days = int(a.get("days") or 14)
        d1 = d0 + timedelta(days=days)
        if d1 > today:
            n_pending += 1          # 还没到验证日，不算分
            continue
        d0s, d1s = d0.strftime("%Y-%m-%d"), d1.strftime("%Y-%m-%d")
        ap_ = a.get("change_pct")
        ac = actual_change_pct(conn, a.get("hash_name"), d0s, d1s)
        if ac is None or ap_ is None:
            continue
        hit = (ap_ > 0) == (ac > 0) if (ap_ != 0 and ac != 0) else None
        rows.append({
            "date": a.get("date"), "hash_name": a.get("hash_name"),
            "name": a.get("name"), "days": days,
            "pred": round(float(ap_), 2), "actual": round(ac, 2),
            "err": round(abs(ac - float(ap_)), 2),
            "bias": round(ac - float(ap_), 2),
            "hit": hit,
        })

    n_hit = [r for r in rows if r["hit"] is not None]
    out = {
        "generated": today.strftime("%Y-%m-%d %H:%M"),
        "n_archive": len(arch),
        "n_pending": n_pending,
        "n_verifiable": len(rows),
        "channel": CHANNEL,
    }
    if n_hit:
        hits = sum(1 for r in n_hit if r["hit"])
        out["direction_hit_rate"] = round(hits / len(n_hit) * 100, 1)
        out["n_direction"] = len(n_hit)
    if rows:
        out["mae_pct"] = round(statistics.mean(r["err"] for r in rows), 2)
        out["bias_pct"] = round(statistics.mean(r["bias"] for r in rows), 2)
        ups = [r for r in rows if r["actual"] > 0]
        if ups:
            out["actual_up_ratio"] = round(len(ups) / len(rows) * 100, 1)
    # 最近 20 条明细，便于人工抽查
    out["recent"] = sorted(rows, key=lambda r: r["date"], reverse=True)[:20]

    _write(out)
    print(json.dumps({k: v for k, v in out.items() if k != "recent"},
                     ensure_ascii=False, indent=2))

    if args.push:
        _push(out)
    if args.notify:
        _notify(out)
    return 0


def _write(out):
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("[FC-Score] 已写出 %s" % OUT)


def _load_env():
    p = os.path.join(REPO, "local_keys.env")
    env = {}
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _push(out):
    env = _load_env()
    tok = env.get("GH_TOKEN")
    if not tok:
        print("[FC-Score] 跳过推送：无 GH_TOKEN")
        return
    sys.path.insert(0, REPO)
    try:
        from github_api_push import api_push_all
        ok, failed = api_push_all(
            files=["kronos_scorecard.json"],
            message="chore: update kronos scorecard",
            repo="hintime/cs2-dashboard", token=tok, base_dir=REPO)
        print("[FC-Score] 推送 %s failed=%s" % (ok, failed))
    except Exception as e:
        print("[FC-Score] 推送异常: %s" % str(e)[:140])


def _notify(out):
    env = _load_env()
    key = env.get("WECOM_WEBHOOK") or env.get("WECOM_KEY") or ""
    if not key:
        print("[FC-Score] 跳过企微：无 WECOM key")
        return
    try:
        import urllib.request
        lines = [
            "【Kronos 预测记分卡】",
            "归档预测 %d 条，待验证 %d 条，可验证 %d 条" % (
                out.get("n_archive", 0), out.get("n_pending", 0), out.get("n_verifiable", 0)),
        ]
        if "direction_hit_rate" in out:
            lines.append("方向命中率 %.1f%%（n=%d）" % (
                out["direction_hit_rate"], out.get("n_direction", 0)))
        if "mae_pct" in out:
            lines.append("幅度误差 %.2f%% · 方向偏差 %+.2f%%" % (
                out["mae_pct"], out.get("bias_pct", 0)))
        if out.get("n_verifiable", 0) == 0:
            lines.append("（样本还不够积累，继续攒）")
        body = json.dumps({"msgtype": "text", "text": {"content": "\n".join(lines)}})
        r = urllib.request.Request(key if key.startswith("http") else key,
                                   data=body.encode("utf-8"),
                                   headers={"Content-Type": "application/json"})
        urllib.request.urlopen(r, timeout=20).read()
        print("[FC-Score] 企微已推送")
    except Exception as e:
        print("[FC-Score] 企微失败: %s" % str(e)[:120])


if __name__ == "__main__":
    sys.exit(main())
