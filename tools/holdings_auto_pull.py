# -*- coding: utf-8 -*-
"""自动拉取浏览器推送的持仓快照并合并（服务器侧，cron 每 15 分钟跑）。

为什么要有这个（2026-10-07）
--------------------------
浏览器上「⬆ 同步到服务器」按钮把持仓推成仓库里的 `holdings_inbox.json`，
但服务器有 5 条采集轮在跑（prices 30min / index 2h / all 6h / history 1h / 加密 10min），
它们读的都是本地 `holdings.json`。所以：

    浏览器推了 ≠ 服务器用上了

义轩的要求是「肯定要扩，以后都扩」—— 新买/卖出后自动生效，不该靠人记得点按钮。
本脚本负责：拉 inbox → 比对 → 有变化才合并（合并前自动备份，成本价红线由
holdings_push.py 保证：服务器的 cost 优先，0 不覆盖）。

为什么不能直接覆盖写
------------------
`holdings.json` 里有服务器侧补充的字段（price / rate_1 / rate_7 / rate_30 /
buff_sell / yyyp_sell / price_history…），全部由各采集轮维护。
直接用 inbox 覆盖会把这些字段清零 → 价格全丢、盈亏算不出来。
所以必须走 holdings_push.py 的**逐条合并**。

只读不写的情况占多数（inbox 没变）→ 直接跳过，不做任何备份与写盘。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOLD = os.path.join(REPO, 'holdings.json')
# 数据源（2026-10-07 改）：浏览器「⬆ 同步到服务器」→ Worker KV。
#   原设计走 GitHub raw holdings_inbox.json，但浏览器推送依赖 ghToken，
#   义轩没配 → 实测 HTTP 401，inbox 永远不存在。
#   改从 Worker GET /api/holdings-sync 拉同一份 KV 数据：
#   浏览器 POST 该端点零配置（_hpCloudPushNow 一直在用），且 KV 的 ts
#   是 Worker（服务器时钟）生成的，比浏览器 update_time 可靠。
KV_URL = 'https://cs2wyx.asia/api/holdings-sync'
MARK = os.path.join(REPO, '.holdings_inbox_seen.json')
PUSH = os.path.join(REPO, 'tools', 'holdings_push.py')


def read_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def need_change(inbox):
    """判断 inbox 是否比上次处理的新。

    ⚠ 不能只看 update_time —— 浏览器时钟可能不准，而且同一份快照可能被
    重复推送。用「条数 + qty 总和 + 关键条目集合」做指纹更可靠：
    持仓变了指纹就变；单纯重复推送指纹不变 → 直接跳过（省备份与写盘）。
    """
    items = inbox.get('items') or []
    if not isinstance(items, list) or not items:
        return False, None, 'inbox 为空'
    def qty_of(it):
        try:
            return int(float(it.get('qty') or 0))
        except Exception:
            return 0
    fp = {
        'n': len(items),
        'qty': sum(qty_of(x) for x in items if isinstance(x, dict)),
        'keys': sorted(str(x.get('market_hash') or x.get('mh') or '')
                       for x in items if isinstance(x, dict))[:200],
        # KV 响应没有 update_time，ts（毫秒）是 Worker 生成的 → 更可靠
        'ts': str(inbox.get('ts') or inbox.get('update_time') or ''),
    }
    prev = read_json(MARK, None)
    if prev == fp:
        return False, fp, '指纹未变（已处理过）'
    return True, fp, '指纹变化'


def main():
    try:
        req = urllib.request.Request(KV_URL, headers={
            'User-Agent': 'cs2-holdings-auto/1.0',
            'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(req, timeout=25) as r:
            inbox = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        # 拉不到不是错误（可能浏览器还没推过、或者网络抖动）→ 安静跳过
        print('[AP] 拉取 KV 失败（跳过本轮）: %s' % str(e)[:90])
        return 0

    changed, fp, why = need_change(inbox)
    if not changed:
        print('[AP] 无需合并：%s' % why)
        return 0

    print('[AP] 检测到持仓变化（%s）→ 合并' % why)
    # 落临时文件再交给 holdings_push.py（它负责备份 + 成本价红线 + 原子写）
    tmp = '/tmp/holdings_inbox_%d.json' % int(time.time())
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(inbox, f, ensure_ascii=False)
    rc = subprocess.run(
        [sys.executable, PUSH, '--file', tmp],
        capture_output=True, text=True, cwd=REPO, timeout=120).returncode
    try:
        os.remove(tmp)
    except Exception:
        pass
    if rc != 0:
        print('[AP] 合并失败 rc=%d（**未改动 holdings.json**）' % rc)
        return 1
    try:
        with open(MARK, 'w', encoding='utf-8') as f:
            json.dump(fp, f, ensure_ascii=False)
    except Exception:
        pass
    d = read_json(HOLD, {}) or {}
    items = d.get('items') or []
    qty = 0
    for h in items:
        try:
            qty += int(float(h.get('qty') or 0))
        except Exception:
            pass
    print('[AP] 合并完成：%d 条 / qty %d / 成本合计 ¥%.2f'
          % (len(items), qty, float(d.get('total_cost') or 0)))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)