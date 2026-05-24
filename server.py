#!/usr/bin/env python3
"""
CS2 Dashboard 本地服务器
用法: python server.py
访问: http://localhost:8765

功能:
- 静态文件服务（替代 GitHub Pages）
- 实时 CSQAQ 查价（输入饰品名查 BUFF/悠悠价）
- 数据更新自动检测（60秒轮询）
"""
import json, os, http.server, urllib.request, urllib.parse, socketserver

PORT = 8765
DATA_DIR = os.path.dirname(os.path.abspath(__file__))

# CSQAQ 接口（从环境变量取 token）
CSQ_TOKEN = os.environ.get('CSQ_API_TOKEN', '')
CSQAQ_BATCH = 'https://api.csqaq.com/v2/multi/batch'

class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DATA_DIR, **kwargs)

    def do_GET(self):
        # ── 实时查价 API ──
        if self.path.startswith('/api/live-prices?'):
            self.send_json(self.handle_live_prices())
            return
        if self.path == '/api/ping':
            self.send_json({'ok': True, 'ts': time.time()})
            return
        # ── 静态文件 ──
        super().do_GET()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def handle_live_prices(self):
        """实时查询 CSQAQ 价格"""
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        names = qs.get('names', [''])[0]
        if not names:
            return {'error': 'missing names'}
        hn_list = [n.strip() for n in names.split(',')][:50]
        if not CSQ_TOKEN:
            return {'error': 'CSQ_API_TOKEN not set'}
        try:
            req = urllib.request.Request(
                CSQAQ_BATCH,
                data=json.dumps({'hash_names': hn_list}).encode(),
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + CSQ_TOKEN,
                },
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())
        except Exception as e:
            return {'error': str(e)}

    def send_json(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

if __name__ == '__main__':
    import time
    print(f'🚀 CS2 Dashboard 本地服务器')
    print(f'   访问: http://localhost:{PORT}')
    print(f'   退出: Ctrl+C')
    print()
    with socketserver.TCPServer(('', PORT), DashboardHandler) as httpd:
        httpd.serve_forever()
