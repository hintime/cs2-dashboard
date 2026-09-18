# -*- coding: utf-8 -*-
"""用 CSQAQ /api/v1/info/chart 给推荐标的补「BUFF 求购价 / 求购数量」。

为什么用它（而不是 SteamDT）：官方文档显示 info/chart 的 key 支持 buy_price/buy_num、
platform=1 即 BUFF，且**未标注企业权限**；实测本 token 可调用，还返回**历史时序**。
SteamDT 只能给当前值且批量接口限「每分钟 1 次」。

流程：market.json 推荐 → 批量接口取 goodId → 逐个 good_id 取 buy_price/buy_num(period=7)
      → 取最后一个非空值 → 合并进 csqaq_boards.json + eco_tracked.json
"""
import os, sys, json, time

R = r'C:\Users\Lenovo\cs2-runner-local'
sys.path.insert(0, R)
os.chdir(R)
for line in open(os.path.join(R, 'local_keys.env'), encoding='utf-8'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
import recommend as rec  # noqa: E402

TOK = os.environ.get('CSQ_API_TOKEN', '')
CAP = int(os.environ.get('CSQ_BUY_CAP') or '40')


def call(path, body):
    return rec.http_post_raw('https://api.csqaq.com' + path, body,
                             headers={'ApiToken': TOK}, timeout=25)


def last_num(series):
    for v in reversed(series or []):
        if isinstance(v, (int, float)) and v > 0:
            return v
    return None


mkt = json.load(open('market.json', encoding='utf-8'))
recs = (mkt.get('recommendations') or {}).get('all') or []
names = [r.get('hash_name') for r in recs if r.get('hash_name')][:CAP]
print('目标 %d 件' % len(names), flush=True)

# ① 批量取 goodId（50/次）
gid_map = {}
for i in range(0, len(names), 50):
    batch = names[i:i + 50]
    r = call('/api/v1/goods/getPriceByMarketHashName', {'marketHashNameList': batch})
    for k, v in ((r.get('data') or {}).get('success') or {}).items():
        if v.get('goodId'):
            gid_map[k] = v['goodId']
    time.sleep(0.4)
print('取到 goodId: %d 件' % len(gid_map), flush=True)

# ② 逐个取 BUFF 求购价/求购数量
out = {}
t0 = time.time()
for n, (hn, gid) in enumerate(gid_map.items(), 1):
    row = {}
    for key, dst in (('buy_price', 'buff_buy'), ('buy_num', 'buff_buy_num')):
        try:
            r = call('/api/v1/info/chart', {'good_id': gid, 'key': key, 'platform': 1,
                                            'period': 7, 'style': 'all_style'})
            val = last_num((r.get('data') or {}).get('main_data'))
            if val is not None:
                row[dst] = float(val) if dst == 'buff_buy' else int(val)
        except Exception as e:
            print('   %s %s 失败: %s' % (hn[:24], key, str(e)[:60]), flush=True)
        time.sleep(0.35)
    if row:
        out[hn] = row
    if n % 10 == 0:
        print('  进度 %d/%d  %.0fs' % (n, len(gid_map), time.time() - t0), flush=True)

print('拿到买盘 %d 件（%.0fs）' % (len(out), time.time() - t0), flush=True)

# ③ 落旁路（逐键合并，勿覆盖其他字段）+ 回写 eco_tracked
try:
    import update as U
    U.save_csqaq_boards(out)
    et = json.load(open('eco_tracked.json', encoding='utf-8'))
    n = 0
    for it in et:
        d = out.get(it.get('HashName', ''))
        if d:
            it.update(d)
            it['_buy_src'] = 'csqaq_chart'
            n += 1
    U.write_json('eco_tracked.json', et)
    print('已写入 csqaq_boards.json 与 eco_tracked.json（%d 件）' % n)
except Exception as e:
    print('落盘失败:', e)
print('DONE')
