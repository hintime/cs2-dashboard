#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""企业微信「接收消息服务器」回调服务 —— 支持**双向指令**。

演进
----
v1：只实现 GET 验证（用来解锁「企业可信IP」）。
v2（本版）：补上 POST 消息处理 —— 你发指令，它回数据。

为什么必须用「异步主动推送」而不是「被动回复」
--------------------------------------------
企业微信要求被动回复必须 **5 秒内**返回，而我们查数据（读 market.json / 跑就绪度
统计）可能超时。所以策略是：**立即返回空串（表示不回复），再由后台线程用
`message/send` 主动推送**。用户体验完全一样（都是收到一条消息），但不受 5 秒限制。

安全
----
- 只处理固定路径，其余 404
- POST 必须通过 sha1 验签才解密
- 指令只读数据，不做任何写操作/执行外部命令（就绪度除外，走固定脚本）
"""

import base64
import binascii
import collections
import hashlib
import json
import os
import struct
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from Crypto.Cipher import AES

sys.path.insert(0, '/home/ubuntu/cs2-watchdog')

CONF = '/home/ubuntu/cs2-run/watchdog/wecom_callback.env'
LOG = '/home/ubuntu/cs2-run/watchdog/wecom_callback.log'
PATH = '/wecom-callback'
RUN = '/home/ubuntu/cs2-run'
VENV_PY = '/home/ubuntu/cs2-run/venv/bin/python'

# 主消息去重（企业微信会重试），只保留最近 200 条
_seen = collections.OrderedDict()
_seen_lock = threading.Lock()


def load_conf():
    c = {}
    with open(CONF, encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith('#') and '=' in s:
                k, v = s.split('=', 1)
                c[k.strip()] = v.strip()
    return c


def log(msg):
    line = '[%s] %s' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg)
    print(line, flush=True)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def verify_signature(token, ts, nonce, encrypt, signature):
    arr = sorted([token, ts, nonce, encrypt])
    return hashlib.sha1(''.join(arr).encode('utf-8')).hexdigest() == signature


def decrypt(encrypt_b64, key, receive_id):
    aes = AES.new(key, AES.MODE_CBC, key[:16])
    plain = aes.decrypt(base64.b64decode(encrypt_b64))
    pad = plain[-1]
    if pad < 1 or pad > 32:
        raise ValueError('bad padding')
    plain = plain[:-pad]
    msg_len = struct.unpack('>I', plain[16:20])[0]
    msg = plain[20:20 + msg_len].decode('utf-8')
    rid = plain[20 + msg_len:].decode('utf-8')
    if receive_id and rid != receive_id:
        raise ValueError('receiveid mismatch')
    return msg


# ══════════════════ 指令处理 ══════════════════

def load_json(name, default=None):
    try:
        with open(os.path.join(RUN, name), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def fmt_age(iso):
    try:
        import datetime
        t = datetime.datetime.fromisoformat(str(iso).replace('Z', '+00:00'))
        if t.tzinfo is None:
            t = t.replace(tzinfo=datetime.timezone.utc)
        age = (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() / 60
        return "%.0f 分钟前" % age if age < 120 else "%.1f 小时前" % (age / 60)
    except Exception:
        return "?"


def cmd_help():
    return ("【CS2 看板 · 指令】\n"
            "查询 <名字>   查现价，如「查询 AK红」\n"
            "今天          当日概况\n"
            "持仓          持仓盈亏\n"
            "就绪度        Kronos 训练进度\n"
            "帮助          这条")


def cmd_today():
    st = load_json('data_status.json', {}) or {}
    mk = load_json('market.json', {}) or {}
    recs = ((mk.get('recommendations') or {}).get('all')) or []
    lines = ["【CS2 看板 · 今天】"]
    lines.append("数据更新   %s" % fmt_age(st.get('updated')))
    lines.append("推荐条数   %d" % len(recs))
    miss = sum(1 for r in recs if not r.get('n_steam'))
    if recs:
        lines.append("Steam基准  缺 %d 条" % miss)
    if recs:
        lines.append("— 前 3 名 —")
        for r in recs[:3]:
            nm = r.get('name') or r.get('market_hash_name') or '?'
            sc = r.get('score')
            px = r.get('price')
            seg = "  %s" % nm[:24]
            if sc is not None:
                seg += "  分 %s" % (round(sc) if isinstance(sc, (int, float)) else sc)
            if px:
                seg += "  ¥%s" % px
            lines.append(seg)
    return "\n".join(lines)


def cmd_holdings():
    h = load_json('holdings.json', None)
    if not h:
        return "没读到 holdings.json"
    items = h if isinstance(h, list) else (h.get('items') or h.get('holdings') or [])
    if not items:
        return "持仓列表为空"
    lines = ["【CS2 看板 · 持仓】"]
    tot_cost = tot_val = 0.0
    for it in items[:15]:
        nm = it.get('HashName') or it.get('name') or it.get('item_name') or '?'
        cost = it.get('cost') or it.get('buy_price') or 0
        val = it.get('price') or it.get('current_price') or it.get('buff_sell') or 0
        try:
            tot_cost += float(cost or 0)
            tot_val += float(val or 0)
        except Exception:
            pass
        pnl = ""
        if cost and val:
            try:
                pct = (float(val) - float(cost)) / float(cost) * 100
                pnl = "  %+.1f%%" % pct
            except Exception:
                pass
        lines.append("  %s  ¥%s%s" % (str(nm)[:22], val or '?', pnl))
    if tot_cost:
        lines.append("— 合计 —")
        lines.append("  成本 ¥%.0f / 现价 ¥%.0f (%+.1f%%)"
                     % (tot_cost, tot_val, (tot_val - tot_cost) / tot_cost * 100))
    return "\n".join(lines)


def cmd_ready():
    try:
        r = subprocess.run([VENV_PY, os.path.join(RUN, 'tools', 'kronos_ready.py')],
                           capture_output=True, timeout=120,
                           env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        out = (r.stdout or b'').decode('utf-8', 'replace').strip()
        if not out:
            return "就绪度脚本无输出（rc=%d）" % r.returncode
        # 只取关键几行，避免太长
        keep = [l for l in out.split('\n')
                if any(k in l for k in ['就绪度', '最长', '当前速度', '还差',
                                        '按当前速度', '若提高', '已达标'])]
        return '\n'.join(keep) if keep else out[:300]
    except Exception as e:
        return "就绪度查询失败: %s: %s" % (type(e).__name__, e)


def _norm(s):
    return ''.join(ch for ch in str(s).lower() if ch.isalnum())


# ★ 中文别名表：饰品名是英文的，不加这层「AK红」这种中文简称永远查不到。
#   玩家口径，按需增补。值可以是多个英文关键词（空格分隔）。
ALIAS = {
    # ── 武器 ──
    'ak': 'ak-47', 'ak47': 'ak-47',
    'm4a4': 'm4a4', 'm4': 'm4a4',
    'm4a1': 'm4a1-s', '消音': 'm4a1-s',
    'awp': 'awp', '大狙': 'awp',
    '沙鹰': 'desert eagle', 'deagle': 'desert eagle',
    '野牛': 'pp-bizon', 'bizon': 'pp-bizon',
    '法玛斯': 'famas', '加利尔': 'galil', '咖喱': 'galil',
    '鸟狙': 'ssg 08',
    '车王': 'mp9', '微冲': 'mac-10',
    '内格夫': 'negev', '大菠萝': 'negev',
    '吹风机': 'p90',
    '爪子': 'p250', 'usp': 'usp-s',
    '格洛克': 'glock', '沙鹰枪': 'desert eagle',
    # ── 刀 ──
    '蝴蝶': 'butterfly knife', '蝴蝶刀': 'butterfly knife',
    '爪刀': 'karambit', '爪子刀': 'karambit', '卡拉': 'karambit',
    'm9': 'm9 bayonet',
    '折叠刀': 'flip knife', '折叠': 'flip knife',
    '刺刀': 'bayonet', '弯刀': 'bayonet',
    '猎杀者': 'huntsman knife', '猎杀': 'huntsman knife',
    '短剑': 'stiletto knife', '骷髅': 'skeleton knife',
    '熊刀': 'ursus knife', '熊': 'ursus knife',
    '军刀': 'talon knife', '塔隆': 'talon knife',
    '系绳': 'nomad knife', '流浪者': 'nomad knife',
    '求生': 'survival knife',
    '雇佣兵': 'paracord knife',
    '经典': 'classic knife',
    '折刀': 'navaja knife',
    # ── 皮肤 ──
    '红': 'redline', '红线': 'redline',
    '二西': 'asiimov', '二西莫夫': 'asiimov', '阿西莫夫': 'asiimov',
    '火神': 'vulcan',
    '血腥': 'bloodsport', '血腥运动': 'bloodsport',
    '渐变': 'fade', '多普勒': 'doppler',
    '传说': 'lore', '屠夫': 'slaughter',
    '龙狙': 'dragon lore', '巨龙': 'dragon lore',
    '咆哮': 'howl', '深红之网': 'crimson web', '红网': 'crimson web',
    '网格': 'web',
    '霓虹': 'neon', '霓虹骑士': 'neon rider',
    '水灵': 'aquamarine', '海蓝': 'aquamarine',
    '印花集': 'printstream', '印花流': 'printstream',
    '自动化': 'autotronic', '自动化刀': 'autotronic',
    '伽玛': 'gamma', '伽马': 'gamma',
    '大理石': 'marble fade', '大理石渐变': 'marble fade',
    '虎牙': 'tiger tooth', '虎牙刀': 'tiger tooth',
    '黑压': 'black laminate', '黑珍珠': 'black pearl',
    '蓝宝': 'sapphire', '红宝': 'ruby', '绿宝': 'emerald',
    # ── 磨损（用于缩小范围）──
    '崭新': 'factory new', '崭新出厂': 'factory new',
    '略磨': 'minimal wear', '略有磨损': 'minimal wear',
    '久经': 'field-tested', '久经沙场': 'field-tested',
    '破旧': 'well-worn', '破损不堪': 'well-worn',
    '战痕': 'battle-scarred', '战痕累累': 'battle-scarred',
    'stattrak': 'stattrak', '数珠': 'stattrak', '★': 'stattrak',
}


def cmd_query(kw):
    """在 eco_tracked / market 里模糊找标的并报价格。"""
    kw = kw.strip()
    if not kw:
        return "用法：查询 <名字>，例如「查询 AK红」"
    cands = []
    et = load_json('eco_tracked.json', []) or []
    for it in (et if isinstance(et, list) else []):
        nm = it.get('HashName') or it.get('name') or ''
        gn = it.get('GoodsName') or ''          # ★ 2026-09-21：中文名，原来完全没用
        if nm or gn:
            cands.append((nm, gn, it))
    if not cands:
        mk = load_json('market.json', {}) or {}
        for r in (((mk.get('recommendations') or {}).get('all')) or []):
            nm = r.get('name') or r.get('market_hash_name') or ''
            gn = r.get('name_cn') or r.get('goods_name') or ''
            if nm or gn:
                cands.append((nm, gn, r))

    # ★ 关键词展开：中文别名 → 英文关键词，再叠加输入里的英数字片段
    import re as _re
    kws = []
    low = kw.lower()
    kw_n = _norm(kw)                            # ★ 输入整体归一（中文也适用）
    for cn, en in ALIAS.items():
        if cn != '★' and cn in low:
            kws.extend(en.split())
    for p in _re.findall(r'[a-z0-9]+', low):
        if len(p) >= 2:
            kws.append(p)
    seen, KWS = set(), []
    for k in kws:
        if k and k not in seen:
            seen.add(k)
            KWS.append(k)

    # ★ 2026-09-21：只有「英文关键词为空 且 整体串也太短」才算听不出。
    #   原来只要 KWS 为空就放弃 —— 用户发纯中文皮肤名必然 KWS 为空，
    #   哪怕库里就有「MP9 | 毛细血管」也永远查不到。
    if not KWS and len(kw_n) < 2:
        return ("没听出关键词「%s」\n"
                "试试加个武器或皮肤名，例如「AK红」「蝴蝶刀多普勒」\n"
                "或先发「今天」看推荐里有什么" % kw)

    # ── 收集全部命中（不只最优一个）──
    hit_list = []
    for nm, gn, it in cands:
        nm_n = _norm(nm)
        gn_n = _norm(gn)
        # ★ 词边界匹配：原名保留空格/连字符，`\bak\b` 命中 `AK-47` 但**不**命中 `Snake`
        #   （原来用归一化子串，'ak' 会误伤 snake / break / black 等一大片）
        h = sum(1 for k in KWS
                if _re.search(r'\b' + _re.escape(k) + r'\b', nm, _re.I))
        zh = bool(kw_n) and len(kw_n) >= 2 and kw_n in gn_n
        if h == 0 and not zh:
            continue
        score = h * 10 + (100 if zh else 0)
        if h and len(KWS) and h == len(KWS):
            score += 50
        hit_list.append((score, nm, gn, it))
    if not hit_list:
        return ("没找到「%s」\n"
                "试过的关键词：%s\n"
                "提示：可以只发武器名（如「蝴蝶刀」）看有哪些皮肤"
                % (kw, '/'.join(KWS[:6])))
    hit_list.sort(key=lambda x: -x[0])

    # ── 按「武器|皮肤」基名归组，再按磨损分档 ──
    #  ★ 2026-09-21 义轩要求：查一个皮肤要给出三档磨损价格
    #  （破损不堪 / 战痕累累 已被采集层排除，库里只有三档）
    WEARS = ('崭新出厂', '略有磨损', '久经沙场', '破损不堪', '战痕累累')

    def _base(gn, nm):
        b = gn or nm
        for w in WEARS:
            b = b.replace('(%s)' % w, '').replace('（%s）' % w, '')
        return b.strip() or nm

    def _wear(gn):
        for w in WEARS:
            if w in (gn or ''):
                return w
        return ''

    groups = {}
    for sc, nm, gn, it in hit_list:
        b = _base(gn, nm)
        w = _wear(gn)
        g = groups.setdefault(b, {})
        if w not in g or g[w][0] < sc:
            g[w] = (sc, nm, gn, it)

    def _gscore(g):
        # ★ 最高分为主（避免「多档弱相关」压过「单档强相关」），命中档数仅作次要加权
        return max(v[0] for v in g.values()) * 100 + len(g)

    best_base = max(groups, key=lambda b: _gscore(groups[b]))
    g = groups[best_base]

    def pick(d, *keys):
        for k in keys:
            v = d.get(k)
            if v not in (None, '', 0):
                return v
        return None

    def _fmt(v):
        if v in (None, ''):
            return '—'
        try:
            return '¥%g' % float(v)
        except Exception:
            return str(v)

    L = ['名称   %s' % best_base]
    for w in WEARS[:3]:
        if w in g:
            _sc, nm, gn, it = g[w]
            L.append('  %s  BUFF %s / 悠悠 %s / Steam %s' % (
                w,
                _fmt(pick(it, 'buff_sell', 'buff_price', '_steamdt_buff')),
                _fmt(pick(it, 'yyyp_sell', 'yy_sell', 'yyyp_price')),
                _fmt(pick(it, 'steam_sell', 'n_steam', '_steam_sell'))))
        else:
            L.append('  %s  （无数据）' % w)
    others = [b for b in groups if b != best_base]
    if others:
        L.append('另有：%s' % '、'.join(others[:3]))
    if len(L) == 1:
        L.append('（这条记录里没有可用价格字段）')
    return '\n'.join(L)


def handle_command(text):
    t = (text or '').strip()
    if not t:
        return None
    low = t.lower()
    if low in ('帮助', 'help', '?', '？'):
        return cmd_help()
    if low in ('今天', '今日', '简报', '日报'):
        return cmd_today()
    if low in ('持仓', '仓位', '盈亏'):
        return cmd_holdings()
    if low in ('就绪度', 'kronos', '训练', '进度'):
        return cmd_ready()
    if t.startswith('查询') or t.startswith('查'):
        kw = t[2:] if t.startswith('查询') else t[1:]
        return cmd_query(kw)
    # 兜底：当成查询关键词
    return cmd_query(t)


def process_async(from_user, text):
    """后台处理指令并主动推送。"""
    try:
        reply = handle_command(text)
        if not reply:
            return
        import wecom_notify
        ok, info = wecom_notify.send(reply, touser=from_user or '@all')
        log('回复 %s -> %s (%s)' % (from_user, 'OK' if ok else 'FAIL', info))
    except Exception as e:
        log('处理指令异常: %s: %s' % (type(e).__name__, e))


# ══════════════════ HTTP ══════════════════

class Handler(BaseHTTPRequestHandler):
    server_version = 'wecom-callback/2.0'

    def _send(self, code, body, ctype='text/plain; charset=utf-8'):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path != PATH:
            log('GET %s -> 404' % self.path)
            return self._send(404, 'not found')
        q = parse_qs(u.query)
        sig = (q.get('msg_signature') or [''])[0]
        ts = (q.get('timestamp') or [''])[0]
        nonce = (q.get('nonce') or [''])[0]
        echo = (q.get('echostr') or [''])[0]
        if not (sig and ts and nonce and echo):
            log('GET 缺参数 -> 400')
            return self._send(400, 'missing params')
        c = load_conf()
        if not verify_signature(c['WECOM_CALLBACK_TOKEN'], ts, nonce, echo, sig):
            log('GET 验签失败 (可能 Token 填错)')
            return self._send(403, 'signature mismatch')
        try:
            key = base64.b64decode(c['WECOM_CALLBACK_AESKEY'] + '=')
            plain = decrypt(echo, key, c.get('WECOM_CORP_ID', ''))
        except Exception as e:
            log('GET 解密失败: %s: %s' % (type(e).__name__, e))
            return self._send(500, 'decrypt failed')
        log('★ GET 验签+解密成功（企业微信显示「保存成功」）')
        return self._send(200, plain)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != PATH:
            return self._send(404, 'not found')
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n) if n else b''
        q = parse_qs(u.query)
        sig = (q.get('msg_signature') or [''])[0]
        ts = (q.get('timestamp') or [''])[0]
        nonce = (q.get('nonce') or [''])[0]

        # ── 先返回，避免 5 秒超时 ──
        self._send(200, '')

        try:
            c = load_conf()
            token = c['WECOM_CALLBACK_TOKEN']
            key = base64.b64decode(c['WECOM_CALLBACK_AESKEY'] + '=')
            corpid = c.get('WECOM_CORP_ID', '')
            root = ET.fromstring(raw.decode('utf-8', 'replace'))
            enc = (root.findtext('Encrypt') or '').strip()
            if not enc:
                log('POST 无 Encrypt 节点')
                return
            if not verify_signature(token, ts, nonce, enc, sig):
                log('POST 验签失败（丢弃）')
                return
            plain = decrypt(enc, key, corpid)
            r2 = ET.fromstring(plain)
            from_user = (r2.findtext('FromUserName') or '').strip()
            mtype = (r2.findtext('MsgType') or '').strip()
            content = (r2.findtext('Content') or '').strip()
            msgid = (r2.findtext('MsgId') or '').strip()

            # 去重（企业微信 5 秒未响应会重试）
            if msgid:
                with _seen_lock:
                    if msgid in _seen:
                        log('POST 重复消息 %s，忽略' % msgid)
                        return
                    _seen[msgid] = time.time()
                    while len(_seen) > 200:
                        _seen.popitem(last=False)

            log('POST 收到 from=%s type=%s content=%r' % (from_user, mtype, content[:60]))
            if mtype != 'text':
                threading.Thread(target=process_async,
                                 args=(from_user, '帮助'), daemon=True).start()
                return
            threading.Thread(target=process_async,
                             args=(from_user, content), daemon=True).start()
        except Exception as e:
            log('POST 处理异常: %s: %s' % (type(e).__name__, e))

    def log_message(self, fmt, *args):
        pass


def main():
    c = load_conf()
    port = int(c.get('PORT') or 80)
    log('启动 v2（支持双向指令）：监听 0.0.0.0:%d，路径 %s' % (port, PATH))
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()


if __name__ == '__main__':
    main()
