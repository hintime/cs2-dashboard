#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ollama 常驻启动器 / 自愈守护（无窗口）

⚠️ 事故背景（2026-09-17，别再踩）：
   Ollama 自带 GUI（`ollama app.exe`）会**自己拉起 serve 并独占 11434**。
   若在它存活时又手动起一个 serve，GUI 抢不到端口就会**每秒重试一次**，
   每次都拉一个控制台进程 → **疯狂弹窗**。日志特征：
       app.log:    msg="ollama exited" err="exit status 1"   （每秒一条）
       server.log: Error: listen tcp 127.0.0.1:11434: bind: Only one usage of each socket address
   → 因此本脚本**启动前一定先确认端口是否已被占用**，绝不在有监听者时再起一个。
   → 本机已把 GUI 的登录自启 `Startup\\Ollama.lnk` 改名为 `.disabled` 让位。

用法：
    pythonw ollama_serve.py            # 起一次就退出（幂等）
    pythonw ollama_serve.py --watch    # 常驻自愈：每 60s 探活，挂了自动拉起（推荐，供登录自启调用）
    python  ollama_serve.py --status   # 打印状态
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

# 常驻进程铁律：Windows 中文环境下 stdout=cp936，非 GBK 字符会让 print 抛异常并静默退出
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

EXE = os.environ.get('OLLAMA_EXE') or r'E:\Ollama\app\ollama.exe'
HOST = os.environ.get('OLLAMA_HOST') or 'http://127.0.0.1:11434'
MODELS = os.environ.get('OLLAMA_MODELS') or r'E:\Ollama\models'
KEEP_ALIVE = os.environ.get('OLLAMA_KEEP_ALIVE') or '10m'
WATCH_SEC = int(os.environ.get('OLLAMA_WATCH_SEC') or '60')
HERE = os.path.dirname(os.path.abspath(__file__))

# 本地探活必须绕开系统/沙箱代理：代理对 127.0.0.1 可能返回 502，
# 会让守护误判「服务挂了」从而反复去起 serve（→ 又变成弹窗事故）。
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def log(msg):
    """日志是唯一可观测通道：写文件必须无条件成功，print 单独包 try"""
    line = '%s %s' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg)
    try:
        d = os.path.join(HERE, 'logs')
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'ollama_serve.log'), 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass
    try:
        print(line)
    except Exception:
        pass


def api_tags(timeout=3):
    try:
        with _OPENER.open(HOST + '/api/tags', timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8', 'replace'))
    except Exception:
        return None


def port_in_use(host='127.0.0.1', port=11434, timeout=1.5):
    """端口是否已有监听者（用来避免重复起 serve）"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def start_serve():
    env = dict(os.environ)
    env['OLLAMA_MODELS'] = MODELS          # 显式给：GUI/服务读不到用户级变量时模型列表会是空
    env['OLLAMA_KEEP_ALIVE'] = KEEP_ALIVE  # 覆盖用户可能设成 0 的值（0 = 每次调用都重载模型）
    DETACHED = 0x00000008                  # 控制台程序完全脱离，不产生任何窗口
    p = subprocess.Popen([EXE, 'serve'], env=env, creationflags=DETACHED,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    return p.pid


def ensure(announce=True):
    """确保服务可用。返回 (ok, note)"""
    d = api_tags()
    if d is not None:
        return True, 'ok(models=%d)' % len(d.get('models') or [])
    if port_in_use():
        # 有监听者但 API 不通：绝不再起一个（会与它抢端口）
        return False, 'port-busy-but-api-down（有监听者但 API 不通，已放弃重启以免抢占）'
    if not os.path.exists(EXE):
        return False, 'exe-missing:%s' % EXE
    if announce:
        log('服务不可达 → 启动 serve（MODELS=%s KEEP_ALIVE=%s）' % (MODELS, KEEP_ALIVE))
    try:
        pid = start_serve()
    except Exception as e:
        return False, 'spawn-failed:%s' % str(e)[:120]
    for i in range(40):
        time.sleep(1.5)
        d = api_tags()
        if d is not None:
            return True, 'restarted(pid=%s, models=%d, %.0fs)' % (pid, len(d.get('models') or []), i * 1.5 + 1.5)
    return False, 'restarted-but-not-ready(pid=%s)' % pid


def main():
    if '--status' in sys.argv:
        d = api_tags()
        print('service :', 'online' if d is not None else 'offline')
        print('models  :', [m.get('name') for m in (d or {}).get('models', [])])
        print('port    :', 'in use' if port_in_use() else 'free')
        print('exe     :', EXE, os.path.exists(EXE))
        print('models dir:', MODELS, os.path.isdir(MODELS))
        return 0

    if '--watch' in sys.argv:
        # 单实例互斥：避免登录自启 + 手动启动同时留下两个守护（会抢着重启服务）
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            _h = kernel32.CreateMutexW(None, False, 'Global\\cs2_ollama_watch')
            if kernel32.GetLastError() == 183:      # ERROR_ALREADY_EXISTS
                log('已有自愈守护在运行，本次退出')
                return 0
        except Exception:
            pass
        log('自愈守护启动（每 %ds 探活一次，PID=%d）' % (WATCH_SEC, os.getpid()))
        prev_ok = None
        while True:
            ok, note = ensure(announce=(prev_ok is not True))
            if prev_ok is None or ok != prev_ok:
                log('状态: %s' % note)
            prev_ok = ok
            time.sleep(WATCH_SEC)

    ok, note = ensure()
    log('单次执行: %s' % note)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
