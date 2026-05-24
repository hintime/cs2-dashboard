#!/usr/bin/env python3
"""
本地 Steam 代理 — 解决 CORS 限制
原理：浏览器 fetch localhost 不受 CORS 限制，本脚本转发到 Steam（走 Steam++）

使用：
  1. 开着 Steam++（确保能访问 steamcommunity.com）
  2. 终端运行：python steam_proxy.py
  3. 看板里一键导入会优先走这个本地代理
"""

import http.server
import urllib.request
import urllib.error
import ssl
import json
import sys

PORT = 8765
STEAM_HOST = 'steamcommunity.com'

# 不校验证书（Steam++ 本地代理可能有自签名证书）
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        # 只代理 steamcommunity.com 的请求
        target_url = f'https://{STEAM_HOST}{self.path}'
        print(f'[→] {target_url[:80]}...')

        # 转发用户浏览器携带的 Cookie（如果有的话）
        headers = {}
        if self.headers.get('Cookie'):
            headers['Cookie'] = self.headers['Cookie']
        if self.headers.get('User-Agent'):
            headers['User-Agent'] = self.headers['User-Agent']

        req = urllib.request.Request(target_url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30, context=ssl_ctx) as resp:
                data = resp.read()
                self.send_response(resp.status)
                # ⚡ 关键：加上 CORS 头，浏览器就不会拦截
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', '*')
                self.send_header('Content-Type', resp.headers.get('Content-Type', 'application/json'))
                self.send_header('Content-Length', len(data))
                self.end_headers()
                self.wfile.write(data)
                print(f'[✓] {resp.status} {len(data)} bytes')
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            print(f'[✗] HTTP {e.code}')
        except Exception as e:
            self.send_response(502)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'error': str(e)}).encode())
            print(f'[✗] {e}')

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.end_headers()

    def log_message(self, format, *args):
        pass  # 静默，不输出标准日志

if __name__ == '__main__':
    print(f'🚀 Steam 本地代理启动 → http://localhost:{PORT}')
    print(f'   (请保持 Steam++ 运行)')
    print(f'   按 Ctrl+C 停止')
    print()
    server = http.server.HTTPServer(('127.0.0.1', PORT), ProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n👋 代理已停止')
        server.shutdown()
