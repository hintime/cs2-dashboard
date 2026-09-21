#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CS2 看板巡检 + 企业微信告警推送。

检测项（沿用原逻辑，未改动）：
  1. data_status.json 的 updated 距今 > 180 分钟
  2. market.json 推荐条数 != 30
  3. 推荐池混入贴纸/胶囊/印花
  4. n_steam 缺失比例 > 20%

推送策略（避免刷屏）：
  · 状态 OK -> WARN，或问题清单发生变化  → 立即推
  · 持续 WARN 且问题清单不变            → 每 REMIND_HOURS 小时重推一次
  · 状态 WARN -> OK                     → 推一条「已恢复」
  · 其余情况                             → 不推，只写日志
"""

import json
import os
import sys
import time
import datetime
import urllib.request

sys.path.insert(0, '/home/ubuntu/cs2-run/watchdog')

BASE = "https://cs2wyx.asia"
D = "/home/ubuntu/cs2-run/watchdog"
RESULT = os.path.join(D, "last_result.json")
STALE_MIN = 180
EXPECT_RECS = 30
REMIND_HOURS = 6
BAD_KW = ["Sticker", "Patch", "Capsule", "贴纸", "胶囊", "印花"]


def get(path, timeout=25):
    req = urllib.request.Request(BASE + path,
                                 headers={"User-Agent": "cs2-watchdog/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def decide(old_status, old_problems, new_status, problems, last_push, now):
    """返回 (是否推送, 原因)。"""
    if problems and problems != old_problems:
        return True, "新问题/问题变化"
    if problems and (now - (last_push or 0)) > REMIND_HOURS * 3600:
        return True, "问题持续未解决，%.0f 小时重提醒" % REMIND_HOURS
    if not problems and old_problems:
        return True, "已恢复"
    return False, ""


def build_msg(result, old_problems, reason):
    facts = result.get("facts") or {}
    t = datetime.datetime.now().strftime("%m-%d %H:%M")
    if result["status"] == "OK":
        return ("【CS2 看板】已恢复正常\n"
                "时间: %s\n"
                "之前的问题: %s\n"
                "现状: 数据 %.1f 分钟前更新 · 推荐 %s 条 · n_steam 缺 %s 条"
                % (t, "；".join(old_problems) if old_problems else "(无)",
                   facts.get("age_minutes", -1), facts.get("rec_count", "?"),
                   facts.get("n_steam_missing", "?")))
    lines = ["【CS2 看板】发现异常", "时间: " + t, "问题:"]
    for p in result["problems"]:
        lines.append(" · " + p)
    lines.append("现状: 数据 %s 分钟前更新 · 推荐 %s 条 · n_steam 缺 %s 条"
                 % (facts.get("age_minutes", "?"), facts.get("rec_count", "?"),
                    facts.get("n_steam_missing", "?")))
    lines.append("(触发原因: %s)" % reason)
    return "\n".join(lines)


def main():
    problems, facts = [], {}
    try:
        st = get("/data_status.json")
        upd = st.get("updated") or st.get("last_updated") or ""
        facts["data_status_updated"] = upd
        if upd:
            try:
                t = datetime.datetime.fromisoformat(upd.replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=datetime.timezone.utc)
                age = (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() / 60
                facts["age_minutes"] = round(age, 1)
                if age > STALE_MIN:
                    problems.append("数据已 %.0f 分钟未更新（阈值 %d）" % (age, STALE_MIN))
            except Exception as e:
                problems.append("无法解析 data_status.updated: %s" % e)
        else:
            problems.append("data_status.json 里没有 updated 字段")
    except Exception as e:
        problems.append("拉取 data_status.json 失败: %s" % e)

    try:
        mk = get("/market.json")
        recs = (mk.get("recommendations") or {}).get("all") or []
        facts["rec_count"] = len(recs)
        if len(recs) != EXPECT_RECS:
            problems.append("推荐条数 %d（期望 %d）" % (len(recs), EXPECT_RECS))
        bad = [r.get("name") or r.get("market_hash_name") or "?"
               for r in recs
               if any(k in (r.get("name") or r.get("market_hash_name") or "") for k in BAD_KW)]
        if bad:
            problems.append("推荐池混入贴纸/胶囊 %d 条: %s" % (len(bad), bad[:3]))
        miss = sum(1 for r in recs if not r.get("n_steam"))
        facts["n_steam_missing"] = miss
        if recs and miss / len(recs) > 0.2:
            problems.append("Steam 基准价缺失 %d/%d（>20%%）" % (miss, len(recs)))
    except Exception as e:
        problems.append("拉取 market.json 失败: %s" % e)

    # ── 读上一次结果（用于判断是否需要推送）──
    old = {}
    try:
        with open(RESULT, encoding="utf-8") as f:
            old = json.load(f)
    except Exception:
        pass
    old_status = old.get("status") or "OK"
    old_problems = old.get("problems") or []
    last_push = old.get("last_push_ts") or 0

    result = {
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "WARN" if problems else "OK",
        "problems": problems,
        "facts": facts,
        "last_push_ts": last_push,
        "last_pushed_problems": old.get("last_pushed_problems") or [],
        "last_push_info": old.get("last_push_info") or "",
    }

    # ── 推送 ──
    now = time.time()
    should, reason = decide(old_status, old_problems, result["status"], problems,
                            last_push, now)
    push_note = "未推送"
    if should:
        try:
            import wecom_notify
            ok, info = wecom_notify.send(build_msg(result, old_problems, reason))
        except Exception as e:
            ok, info = False, "%s: %s" % (type(e).__name__, e)
        if ok:
            result["last_push_ts"] = now
            result["last_pushed_problems"] = problems
            result["last_push_info"] = "%s | %s" % (reason, info)
            push_note = "已推送(%s)" % reason
        else:
            result["last_push_info"] = "失败: %s" % info
            push_note = "推送失败: %s" % info
    elif problems:
        push_note = "问题未变化且 %d 小时内已推过，跳过" % REMIND_HOURS

    os.makedirs(D, exist_ok=True)
    tmp = RESULT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    os.replace(tmp, RESULT)

    line = "[%s] %s %s [%s]" % (
        result["checked_at"][:19], result["status"],
        " | ".join(problems) if problems else json.dumps(facts, ensure_ascii=False),
        push_note)
    with open(os.path.join(D, "watchdog.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)
    # ── 异动主动推送（2026-09-21 义轩要求：有异动要主动发信息）──
    #   挂在巡检同一趟 cron（每 30 分钟），不新增调度；失败不影响巡检。
    try:
        import alerts
        _n = alerts.run()
        if _n:
            print('  [ALERT] 已推送 %d 条异动' % _n)
    except Exception as _e:
        print('  [ALERT] 运行失败（不影响巡检）: %s: %s'
              % (type(_e).__name__, _e), file=sys.stderr)

    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
