#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""企业微信推送（自建应用）。

用法：
    python3 wecom_notify.py "消息内容"
    echo "内容" | python3 wecom_notify.py
    from wecom_notify import send; send("内容")

要点
----
- 只依赖标准库（crontab 用系统 python3 也能跑）
- access_token 缓存到 .wecom_token.json（有效期 7200s，提前 5 分钟刷新）
- 凭据从 /home/ubuntu/cs2-run/local_keys.env 读（WECOM_CORP_ID / WECOM_SECRET / WECOM_AGENT_ID）
"""

import json
import os
import ssl
import sys
import time
import urllib.request
import urllib.error

KEYS = '/home/ubuntu/cs2-run/local_keys.env'
CACHE = '/home/ubuntu/cs2-run/watchdog/.wecom_token.json'
API = 'https://qyapi.weixin.qq.com/cgi-bin'
UA = {'User-Agent': 'cs2-watchdog/1.0'}

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def _conf():
    c = {}
    try:
        with open(KEYS, encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith('#') and '=' in s:
                    k, v = s.split('=', 1)
                    c[k.strip()] = v.strip()
    except Exception:
        pass
    return c


def _token():
    """取 access_token，带磁盘缓存。"""
    now = time.time()
    try:
        with open(CACHE, encoding='utf-8') as f:
            d = json.load(f)
        if d.get('token') and d.get('exp', 0) > now + 300:
            return d['token']
    except Exception:
        pass
    c = _conf()
    cid, sec = c.get('WECOM_CORP_ID', ''), c.get('WECOM_SECRET', '')
    if not (cid and sec):
        raise RuntimeError('local_keys.env 里缺 WECOM_CORP_ID / WECOM_SECRET')
    url = '%s/gettoken?corpid=%s&corpsecret=%s' % (API, cid, sec)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                timeout=20, context=_ctx) as r:
        d = json.loads(r.read().decode('utf-8'))
    if not d.get('access_token'):
        raise RuntimeError('换 token 失败: errcode=%s errmsg=%s'
                           % (d.get('errcode'), d.get('errmsg')))
    try:
        with open(CACHE, 'w', encoding='utf-8') as f:
            json.dump({'token': d['access_token'],
                       'exp': now + int(d.get('expires_in') or 7200)}, f)
        os.chmod(CACHE, 0o600)
    except Exception:
        pass
    return d['access_token']


def send(content, touser='@all'):
    """发文本消息。返回 (ok, 说明)。"""
    c = _conf()
    try:
        aid = int(c.get('WECOM_AGENT_ID') or 0)
    except ValueError:
        aid = 0
    if not aid:
        return False, 'local_keys.env 里缺 WECOM_AGENT_ID'
    body = {'touser': touser, 'msgtype': 'text', 'agentid': aid,
            'text': {'content': content}, 'safe': 0}
    url = '%s/message/send?access_token=%s' % (API, _token())
    req = urllib.request.Request(
        url, data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json', **UA}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=20, context=_ctx) as r:
            d = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        return False, '%s: %s' % (type(e).__name__, e)
    if d.get('errcode') == 0:
        inv = d.get('invaliduser') or ''
        return True, ('ok' if not inv else 'ok 但 invaliduser=%s' % inv)
    return False, 'errcode=%s errmsg=%s' % (d.get('errcode'), d.get('errmsg'))


if __name__ == '__main__':
    msg = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read()
    ok, info = send(msg.strip())
    print(('✓ 已发送: ' if ok else '✗ 发送失败: ') + info)
    sys.exit(0 if ok else 1)
