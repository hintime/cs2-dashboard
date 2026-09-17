#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ollama 常驻启动器（无窗口）

用途：本机 Ollama 的 GUI 启动器出现过「误判已有实例 → 自己退出、serve 实际没起来」，
      这里改为直接拉起 `ollama.exe serve` 并显式带上关键环境变量，规避该问题。

关键环境变量（写死在此，避免依赖用户级变量是否生效）：
    OLLAMA_MODELS      模型目录（默认 E:\\Ollama\\models）
    OLLAMA_KEEP_ALIVE  保留模型时长（用户级原为 0 = 每次调用都重载，很慢）
    OLLAMA_HOST        监听地址

用法：
    pythonw ollama_serve.py      # 无窗口启动（推荐，供开机自启调用）
    python  ollama_serve.py      # 前台运行（调试用）
"""
import os, subprocess, sys, time, urllib.request, json

EXE = os.environ.get('OLLAMA_EXE') or r'E:\Ollama\app\ollama.exe'
HOST = os.environ.get('OLLAMA_HOST') or 'http://127.0.0.1:11434'


def reachable(timeout=2):
    try:
        with urllib.request.urlopen(HOST + '/api/tags', timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8', 'replace'))
    except Exception:
        return None


def log(msg):
    try:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'ollama_serve.log')
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'a', encoding='utf-8') as f:
            f.write('%s %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg))
    except Exception:
        pass


def main():
    if not os.path.exists(EXE):
        log('EXE 不存在: %s' % EXE)
        print('找不到 %s，可用 OLLAMA_EXE 指定' % EXE)
        return 1

    if reachable():
        d = reachable()
        log('已在运行，模型 %d 个' % len(d.get('models') or []))
        print('Ollama 已在运行（%d 个模型）' % len(d.get('models') or []))
        return 0

    env = dict(os.environ)
    env.setdefault('OLLAMA_MODELS', r'E:\Ollama\models')
    env.setdefault('OLLAMA_KEEP_ALIVE', '10m')   # 覆盖可能为 0 的用户级设置
    env.setdefault('OLLAMA_HOST', '127.0.0.1:11434')
    log('启动 serve | MODELS=%s KEEP_ALIVE=%s' % (env['OLLAMA_MODELS'], env['OLLAMA_KEEP_ALIVE']))

    # DETACHED_PROCESS：控制台程序完全脱离，不产生任何窗口
    DETACHED = 0x00000008
    p = subprocess.Popen([EXE, 'serve'], env=env, creationflags=DETACHED,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    log('PID=%d' % p.pid)

    for i in range(60):
        time.sleep(1)
        d = reachable()
        if d:
            n = len(d.get('models') or [])
            names = [m.get('name') for m in (d.get('models') or [])]
            log('就绪（%ds），%d 个模型: %s' % (i + 1, n, ', '.join(names)))
            print('就绪（%ds），%d 个模型: %s' % (i + 1, n, ', '.join(names)))
            return 0
    log('60s 未就绪')
    print('启动后 60s 仍未就绪，看 logs/ollama_serve.log 与 %s 的 server.log'
          % os.path.expandvars(r'%LOCALAPPDATA%\Ollama'))
    return 1


if __name__ == '__main__':
    sys.exit(main())
