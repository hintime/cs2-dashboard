#!/bin/bash
# 持仓自动合并入口（cron 调这个）
#
# 作用：拉仓库里的 holdings_inbox.json（浏览器「⬆ 同步到服务器」按钮推的）
#      合并进 holdings.json，让服务器的采集/K 线/加密采样自动跟随持仓变化。
#
# 为什么需要自动（义轩2026-10-07 要求「肯定要扩，以后都扩」）：
#   浏览器点一次按钮 = 推一份快照；但新买/卖出后如果忘了点，
#   服务器就会一直停在旧持仓 → 加密采集漏采、K 线覆盖不到。
#   所以服务器这边每 15 分钟自动拉一次，新增/卖出无需人工干预。
#
# 安全性：
#   · 只在 inbox 比服务器「新」时才合并（靠 inbox 的 update_time + 条目数判断）；
#   · 合并前自动备份（tools/holdings_push.py 内部做）；
#   · 成本价永远不会被 0 覆盖（见 holdings_push.py 的合并规则）。
set -u
cd /home/ubuntu/cs2-run || exit 1
export PYTHONUTF8=1

/home/ubuntu/cs2-run/venv/bin/python tools/holdings_auto_pull.py