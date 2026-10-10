#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主动预警 —— 把看板从「你去问它」变成「它主动告诉你」。

背景：现有企微是**被动响应**（你发指令它才查：今天/异动/在售异动/求购异动）。
      watchdog/check.py 是**体检告警**（数据有没有坏），不是机会告警。
      本脚本补的是第三类：**机会与风险主动推送**。

预警项（全部读真实产物，阈值可配，不臆造）：
  1. 持仓急跌       —— 持仓件 24h 跌幅超阈值（默认 -8%）
  2. 持仓急涨       —— 持仓件 24h 涨幅超阈值（默认 +12%）
  3. 捡漏机会       —— opportunity.json 里出现高分捡漏（价格处 30 日低位 + Kronos 看涨）
  4. 套利机会       —— opportunity.json 里出现可信的大价差（已过异常挂单三重校验）
  5. 流动性恶化     —— liquidity_score.json 里持仓流动性评分掉档

★ 反刷屏设计（本项目踩过的坑：盘口 bug 曾每 30 分钟刷屏 146+ 次）：
  · 同一 (类型, 标的) 有冷却期（默认 6 小时），冷却内不重复推
  · 单轮总量上限（默认 8 条），超出只推最重要的并注明「另有 N 条」
  · 状态文件 .proactive_state.json 记录上次推送时间，重启不丢
  · 全程 try/except 兜底 + 失败也写状态，绝不因异常静默死掉

用法：
    /usr/bin/python3 /home/ubuntu/cs2-run/watchdog/proactive_alerts.py [--dry-run]
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = "/home/ubuntu/cs2-run"
HERE = os.path.join(REPO, "watchdog")
STATE = os.path.join(HERE, ".proactive_state.json")
sys.path.insert(0, HERE)

# ── 阈值 ──
DROP_PCT = -8.0        # 持仓 24h 跌幅告警线
RISE_PCT = 12.0        # 持仓 24h 涨幅告警线
MIN_PICKUP_SCORE = 8.0 # 捡漏最低综合分
MIN_SPREAD_PCT = 15.0  # 套利最低毛价差（全市场 p90 才 19%，15% 已属显著）
COOLDOWN_SEC = 6 * 3600
MAX_ITEMS = 8


def load_json(p, default=None):
    if not os.path.exists(p):
        return default
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def load_state():
    return load_json(STATE, {}) or {}


def save_state(st):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False)
    except Exception as e:
        print("[PROACT] 状态写入失败: %s" % e)


def in_cooldown(st, key, now):
    last = st.get(key)
    if not last:
        return False
    try:
        return (now - float(last)) < COOLDOWN_SEC
    except Exception:
        return False


def collect(now, st):
    """收集所有预警候选。返回 list of (key, 级别, 文本)。"""
    out = []

    # ── 1/2. 持仓急涨急跌 ──
    hold = load_json(os.path.join(REPO, "holdings.json"), {}) or {}
    items = hold.get("items") or []
    for it in items:
        name = it.get("name") or it.get("market_hash") or "?"
        r = it.get("rate_1")          # 24h 涨跌幅（前端同字段）
        if not isinstance(r, (int, float)):
            continue
        key = "hold:%s" % (it.get("market_hash") or name)
        if r <= DROP_PCT:
            k = key + ":drop"
            if not in_cooldown(st, k, now):
                out.append((k, "风险", "%s 24h 跌 %.1f%%（现价 ¥%.2f）"
                            % (name, r, it.get("price") or 0)))
        elif r >= RISE_PCT:
            k = key + ":rise"
            if not in_cooldown(st, k, now):
                out.append((k, "机会", "%s 24h 涨 +%.1f%%（现价 ¥%.2f）"
                            % (name, r, it.get("price") or 0)))

    # ── 3. 捡漏机会 ──
    opp = load_json(os.path.join(REPO, "opportunity.json"), {}) or {}
    for r in (opp.get("undervalued") or [])[:5]:
        if (r.get("score") or 0) < MIN_PICKUP_SCORE:
            continue
        k = "pickup:%s" % r.get("hash_name")
        if in_cooldown(st, k, now):
            continue
        out.append((k, "机会", "捡漏 %s：现价 ¥%.2f 处 30 日 %.0f%% 低位%s"
                    % (r.get("name"), r.get("current") or 0, r.get("pctile") or 0,
                       ("，Kronos 看涨 %+.1f%%" % r["kronos_pct"])
                       if isinstance(r.get("kronos_pct"), (int, float)) else "")))

    # ── 4. 套利机会 ──
    for r in (opp.get("arbitrage") or [])[:5]:
        if (r.get("spread_pct") or 0) < MIN_SPREAD_PCT:
            continue
        k = "arb:%s" % r.get("hash_name")
        if in_cooldown(st, k, now):
            continue
        out.append((k, "机会", "价差 %s：%s %.1f%%（¥%.2f→¥%.2f）"
                    % (r.get("name"), r.get("best_route"), r.get("spread_pct") or 0,
                       r.get("buff_sell") or 0,
                       r.get("yyyp_sell") or r.get("steam_sell") or 0)))

    # ── 5. 流动性恶化 ──
    liq = load_json(os.path.join(REPO, "liquidity_score.json"), {}) or {}
    for r in (liq.get("items") or []):
        sc = r.get("score")
        if not isinstance(sc, (int, float)) or sc > 30:
            continue        # 只报明显差的（分档见 liquidity_score.py）
        k = "liq:%s" % (r.get("hash_name") or r.get("name"))
        if in_cooldown(st, k, now):
            continue
        out.append((k, "风险", "流动性差 %s：评分 %.0f（%s）"
                    % (r.get("name"), sc, r.get("grade") or "不好卖")))

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印不推送")
    args = ap.parse_args()

    now = datetime.now().timestamp()
    st = load_state()
    try:
        cands = collect(now, st)
    except Exception as e:
        print("[PROACT] 收集异常: %s" % str(e)[:160])
        cands = []

    if not cands:
        print("[PROACT] 无预警")
        save_state(st)
        return 0

    # 风险优先于机会，其次按原始顺序
    order = {"风险": 0, "机会": 1}
    cands.sort(key=lambda x: order.get(x[1], 9))
    shown = cands[:MAX_ITEMS]
    hidden = len(cands) - len(shown)

    lines = ["【CS2 主动预警】%s" % datetime.now().strftime("%m-%d %H:%M")]
    for _, lvl, txt in shown:
        lines.append("· [%s] %s" % (lvl, txt))
    if hidden > 0:
        lines.append("（另有 %d 条，冷却期内不重复推送）" % hidden)
    msg = "\n".join(lines)
    print(msg)

    if args.dry_run:
        print("[PROACT] dry-run：不推送、不写冷却")
        return 0

    ok = False
    try:
        import wecom_notify
        ok, info = wecom_notify.send(msg)
        print("[PROACT] 推送 %s %s" % (ok, info))
    except Exception as e:
        print("[PROACT] 推送失败: %s" % str(e)[:160])

    # 无论推送成功与否都记冷却 —— 推送失败不该导致下轮狂轰
    for k, _, _ in shown:
        st[k] = now
    save_state(st)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
