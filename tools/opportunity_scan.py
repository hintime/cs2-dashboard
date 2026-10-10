#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""机会扫描 —— 捡漏（低估）扫描 + 跨平台价差套利监控。

回答两个问题：
  A. 捡漏：现在哪件**便宜**（价格处自身 30 日区间低位）+ 有货可买 + Kronos 还看涨？
  B. 套利：同一件在 BUFF / 悠悠 / Steam 的价差有多大，有没有搬砖空间？

数据来源（全部真实，不臆造）：
  · price_summary.json  —— 5035 件 × 30 天日线（算价格百分位/区间位置）
  · csqaq_boards.json   —— 4838 件盘口：buff_sell/yyyp_sell/steam_sell/buff_buy + platforms
  · ai_forecast.json    —— Kronos 14 日预测（叠加方向判断）
  · name_map.json       —— 英文 market_hash → 中文名（可选，缺失就显示原名）

★ 老坑提醒：这些文件统一用**英文 market_hash** 作键；holdings.json 的 `name` 是中文，
  直接拿中文名查会 0 命中（与 liquidity_score.py 同一个坑）。本脚本全程用 hash。

★ 诚实口径：
  · 套利算的是**挂牌价毛空间**，不含平台手续费、提现限制、汇率。
    Steam 余额无法直接提现，故 BUFF→Steam 只标注「价差」不标「可搬」。
  · 捡漏的「低估」= 相对自身近期区间的低位，**不等于一定会涨**。

产出：opportunity.json
用法：
    /usr/bin/python3 /home/ubuntu/cs2-run/tools/opportunity_scan.py [--push] [--top N]
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = "/home/ubuntu/cs2-run"
OUT = os.path.join(REPO, "opportunity.json")
# 参与扫描的最低门槛：太便宜的（<5元）价差绝对值没意义，手续费都盖不住
MIN_PRICE = 5.0
# 流动性门槛：得真有货可买、有人收，否则是纸面价差
MIN_SELL_NUM = 3
MIN_BUY_NUM = 1
# 套利最小毛价差（%）：低于这个覆盖不了手续费与风险
MIN_SPREAD_PCT = 3.0
# ★ 异常挂单校验（2026-10-11 实测必须加）：
#   直接取各平台"最低卖价"会被天价挂单带偏 —— 实测出现 BUFF 61.77 / Steam 78.15 /
#   悠悠 799.00 的同款（悠悠报出 10 倍于市场公认价），若照单全收会推给用户
#   "价差 1193%" 这种纯属噪音的假机会。
#   做法：以该件三个平台报价的**中位数**为锚，任一平台偏离锚超过 ANCHOR_DEV 倍
#   即判为可疑报价，该方向隔离到 suspicious，不进主榜。
ANCHOR_DEV = 2.0
# ★ 第二道闸：悠悠报价不得显著高于 Steam。
#   Steam 是公认零售天花板（实测全市场 Steam/BUFF 中位数 +49.2%），国内平台悠悠
#   正常应与 BUFF 基本持平（实测 悠悠/BUFF 中位数仅 +0.9%、p90 +19.1%）。
#   若悠悠报价反超 Steam 一大截，基本可判定是「少量人挂天价滞销」的失真报价
#   —— 实测榜首 P250：buff 13.86 / steam 22.04 / 悠悠 34.58（比 Steam 还贵 57%），
#   这种照单全收会推出「价差 149%」的纯噪音假机会。
YYYP_VS_STEAM_MAX = 1.25
# ★ 第三道闸：毛价差上限。全市场 p90 才 19.1%，超过 50% 已极端，隔离待核查。
MAX_SPREAD_PCT = 50.0
# 捡漏：价格处于自身 30 日区间的百分位低于此值才算「低位」
LOW_PCTILE = 25.0


def load_json(p, default=None):
    if not os.path.exists(p):
        return default
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print("[OPP] 读取失败 %s: %s" % (os.path.basename(p), e))
        return default


def pctile(cur, lo, hi):
    """当前价在 [lo,hi] 区间的位置 0~100。区间退化（lo==hi）时返回 50。"""
    if hi <= lo:
        return 50.0
    return max(0.0, min(100.0, (cur - lo) / (hi - lo) * 100.0))


def scan_undervalued(summary, boards, fc_map, name_map, top):
    """捡漏：价格处自身 30 日低位 + 有流动性 + （若有）Kronos 看涨加权。"""
    out = []
    for h, s in (summary or {}).items():
        prices = [p for p in (s.get("prices") or []) if isinstance(p, (int, float)) and p > 0]
        if len(prices) < 20:            # 样本太短，百分位不可信
            continue
        cur = prices[-1]
        if cur < MIN_PRICE:
            continue
        lo, hi = min(prices), max(prices)
        pct = pctile(cur, lo, hi)
        if pct > LOW_PCTILE:
            continue
        b = (boards or {}).get(h) or {}
        # 流动性过滤：有货可买、有人收
        if (b.get("buff_sell_num") or 0) < MIN_SELL_NUM:
            continue
        if (b.get("buff_buy_num") or 0) < MIN_BUY_NUM:
            continue
        f = fc_map.get(h)
        fc_pct = f.get("change_pct") if f else None
        # 综合分：越低位越高分；Kronos 看涨再加成
        score = (LOW_PCTILE - pct) * 2.0
        reason = "价格处于 30 日区间 %.0f%% 低位" % pct
        if isinstance(fc_pct, (int, float)):
            if fc_pct > 0:
                score += min(fc_pct, 15.0)
                reason += "，且 Kronos 14 日看涨 %+.1f%%" % fc_pct
            else:
                score -= min(abs(fc_pct), 10.0)
                reason += "，但 Kronos 14 日看跌 %.1f%%" % fc_pct
        out.append({
            "hash_name": h,
            "name": name_map.get(h) or h,
            "current": round(cur, 2),
            "low30": round(lo, 2),
            "high30": round(hi, 2),
            "pctile": round(pct, 1),
            "kronos_pct": round(fc_pct, 2) if isinstance(fc_pct, (int, float)) else None,
            "sell_num": b.get("buff_sell_num"),
            "buy_num": b.get("buff_buy_num"),
            "score": round(score, 2),
            "reason": reason,
        })
    out.sort(key=lambda r: -r["score"])
    return out[:top]


def scan_arbitrage(boards, name_map, top):
    """套利：同一件在 BUFF / 悠悠 / Steam 的挂牌价差。

    方向口径（毛空间，未扣费）：
      buff→yyyp : 在 BUFF 按最低卖价买入 → 在悠悠按最低卖价挂出
      buff→steam: 同上到 Steam（⚠ Steam 余额不可提现，只作价差参考，标 can_cash=False）
    """
    out = []
    susp = []   # 疑似异常挂单，隔离待核查，不进主榜
    for h, b in (boards or {}).items():
        bs = b.get("buff_sell") or 0     # BUFF 最低卖价 = 你的买入成本
        by = b.get("buff_buy") or 0      # BUFF 最高求购 = 你立刻出手的收入
        ys = b.get("yyyp_sell") or 0     # 悠悠最低卖价
        ss = b.get("steam_sell") or 0    # Steam 最低卖价
        if bs < MIN_PRICE:
            continue
        # 得真有货、真有人收，否则是纸面价差
        if (b.get("buff_sell_num") or 0) < MIN_SELL_NUM:
            continue
        if (b.get("yyyp_sell_num") or 0) < MIN_SELL_NUM:
            continue
        routes = []
        if ys > 0:
            routes.append({
                "route": "BUFF→悠悠", "buy": round(bs, 2), "sell": round(ys, 2),
                "spread": round(ys - bs, 2),
                "spread_pct": round((ys - bs) / bs * 100, 2),
                "can_cash": True,
                "note": "悠悠可提现，是真正可执行的搬砖方向",
            })
        if ss > 0:
            routes.append({
                "route": "BUFF→Steam", "buy": round(bs, 2), "sell": round(ss, 2),
                "spread": round(ss - bs, 2),
                "spread_pct": round((ss - bs) / bs * 100, 2),
                "can_cash": False,
                "note": "Steam 余额不可直接提现，仅作价差参考",
            })
        # 只保留毛价差够大的方向
        routes = [r for r in routes if r["spread_pct"] >= MIN_SPREAD_PCT]
        if not routes:
            continue

        # ── 异常挂单校验：以三平台报价中位数为锚，踢掉天价/失真报价 ──
        anchor_vals = [v for v in (bs, ys, ss) if v > 0]
        anchor = sorted(anchor_vals)[len(anchor_vals) // 2] if anchor_vals else 0

        def _dev_ok(v):
            if anchor <= 0 or v <= 0:
                return True
            return 1.0 / ANCHOR_DEV <= v / anchor <= ANCHOR_DEV

        # 悠悠失真判定：有 Steam 价作参照时，悠悠不得反超 Steam 太多
        yyyp_bad = False
        if ys > 0 and ss > 0 and ys > ss * YYYP_VS_STEAM_MAX:
            yyyp_bad = True

        suspicious, clean = [], []
        for r in routes:
            # sell 与 buy 两端都要校验，只校验一端会漏掉"成本价失真"的情况
            ok = _dev_ok(r["sell"]) and _dev_ok(r["buy"])
            if r["route"] == "BUFF→悠悠" and yyyp_bad:
                ok = False
            if r["spread_pct"] > MAX_SPREAD_PCT:
                ok = False
            (clean if ok else suspicious).append(
                dict(r, anchor=round(anchor, 2),
                     reject=("悠悠报价高于 Steam %.0f%%" % ((ys / ss - 1) * 100))
                     if (r["route"] == "BUFF→悠悠" and yyyp_bad)
                     else ("价差 %.0f%% 超出合理上限" % r["spread_pct"])))

        # ★ 口径修正：Steam 余额不可提现 + 含约 15% 市场费，其价差是**系统性溢价**
        #   而非可执行套利。只把可提现方向（悠悠）计入套利榜，Steam 单列为溢价参考，
        #   否则「BUFF→Steam 246%」会霸榜，把真正的机会挤掉、还误导人以为能搬。
        cashable = [r for r in clean if r.get("can_cash")]

        if not cashable:
            # 没有可信的可执行方向 → 不进套利榜（Steam 溢价仍记一笔供参考）
            if suspicious:
                susp.append({
                    "hash_name": h,
                    "name": name_map.get(h) or h,
                    "buff_sell": round(bs, 2),
                    "yyyp_sell": round(ys, 2) if ys else None,
                    "steam_sell": round(ss, 2) if ss else None,
                    "anchor": round(anchor, 2),
                    "routes": suspicious,
                })
            continue
        cashable.sort(key=lambda r: -r["spread_pct"])
        best = cashable[0]
        out.append({
            "hash_name": h,
            "name": name_map.get(h) or h,
            "buff_sell": round(bs, 2),
            "buff_buy": round(by, 2) if by else None,
            "yyyp_sell": round(ys, 2) if ys else None,
            "steam_sell": round(ss, 2) if ss else None,
            "sell_num": b.get("buff_sell_num"),
            "best_route": best["route"],
            "spread": best["spread"],
            "spread_pct": best["spread_pct"],
            "can_cash": True,
            "note": best["note"],
            "routes": cashable,
        })
    out.sort(key=lambda r: -r["spread_pct"])
    susp.sort(key=lambda r: -len(r.get("routes") or []))
    return out[:top], susp[:top]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()

    summary = load_json(os.path.join(REPO, "price_summary.json"), {})
    boards = load_json(os.path.join(REPO, "csqaq_boards.json"), {})
    fcd = load_json(os.path.join(REPO, "ai_forecast.json"), {})
    name_map = load_json(os.path.join(REPO, "name_map.json"), {}) or {}

    fc_map = {}
    for it in (fcd.get("items") or []):
        if it.get("hash_name"):
            fc_map[it["hash_name"]] = it

    print("[OPP] 输入：price_summary %d 件 / boards %d 件 / forecast %d 件 / name_map %d 条"
          % (len(summary or {}), len(boards or {}), len(fc_map), len(name_map)))

    under = scan_undervalued(summary, boards, fc_map, name_map, args.top)
    arb, susp = scan_arbitrage(boards, name_map, args.top)

    out = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "thresholds": {
            "min_price": MIN_PRICE,
            "min_sell_num": MIN_SELL_NUM,
            "min_buy_num": MIN_BUY_NUM,
            "min_spread_pct": MIN_SPREAD_PCT,
            "low_pctile": LOW_PCTILE,
        },
        "caveat": "套利为挂牌价毛空间，未扣平台手续费/提现成本；Steam 余额不可提现，"
                  "BUFF→Steam 仅作价差参考。捡漏『低估』指相对自身 30 日区间低位，不等于必涨。",
        "undervalued": under,
        "arbitrage": arb,
        "suspicious": susp,
        "stats": {
            "n_undervalued": len(under),
            "n_arbitrage": len(arb),
            "n_suspicious": len(susp),
            "n_summary": len(summary or {}),
            "n_boards": len(boards or {}),
        },
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("[OPP] 已写出 %s：捡漏 %d 条 / 套利 %d 条 / 隔离待核查 %d 条"
          % (OUT, len(under), len(arb), len(susp)))
    for r in under[:3]:
        print("  捡漏 %s 现价%.2f 区间%.2f~%.2f 百分位%.0f%% %s"
              % (r["name"][:22], r["current"], r["low30"], r["high30"],
                 r["pctile"], ("Kronos%+.1f%%" % r["kronos_pct"]) if r["kronos_pct"] else ""))
    for r in arb[:3]:
        print("  套利 %s %s 价差%.2f%% (%.2f→%.2f)"
              % (r["name"][:22], r["best_route"], r["spread_pct"],
                 r["buff_sell"], r["yyyp_sell"] or r["steam_sell"]))

    if args.push:
        _push()
    return 0


def _push():
    env = {}
    p = os.path.join(REPO, "local_keys.env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    tok = env.get("GH_TOKEN")
    if not tok:
        print("[OPP] 跳过推送：无 GH_TOKEN")
        return
    try:
        sys.path.insert(0, REPO)
        from github_api_push import api_push_all
        ok, failed = api_push_all(files=["opportunity.json"],
                                  message="chore: update opportunity scan",
                                  repo="hintime/cs2-dashboard", token=tok, base_dir=REPO)
        print("[OPP] 推送 %s failed=%s" % (ok, failed))
    except Exception as e:
        print("[OPP] 推送异常: %s" % str(e)[:140])


if __name__ == "__main__":
    sys.exit(main())
