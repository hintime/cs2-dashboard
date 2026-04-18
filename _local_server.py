"""
CS2 Dashboard 本地更新服务
监听 localhost:8765，接收前端请求触发数据更新
"""
import http.server
import socketserver
import subprocess
import sys
import os
import json
from urllib.parse import urlparse, parse_qs

PORT = 8765
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
UPDATE_SCRIPT = os.path.join(SCRIPT_DIR, 'update.py')

class UpdateHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 静默日志
        pass
    
    def do_GET(self):
        parsed = urlparse(self.path)
        
        if parsed.path == '/health':
            # 健康检查
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok'}).encode())
            
        elif parsed.path == '/update':
            # 触发更新 - 全量扫描模式
            try:
                query = parse_qs(parsed.query)
                mode = query.get('mode', ['alerts'])[0]  # 默认 alerts，支持 full
                
                # 全量扫描 = prices + alerts + recommendations
                if mode == 'full':
                    script_mode = 'all'
                    print(f'[Server] Triggering FULL scan (all)...')
                else:
                    script_mode = 'alerts'
                    print(f'[Server] Triggering alerts update...')
                
                # 后台运行 update.py
                subprocess.Popen(
                    [sys.executable, UPDATE_SCRIPT, script_mode],
                    cwd=SCRIPT_DIR,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'triggered', 'mode': mode, 'script_mode': script_mode}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

def main():
    print(f'CS2 Dashboard 本地服务启动，监听 http://localhost:{PORT}')
    print('按 Ctrl+C 停止')
    
    with socketserver.TCPServer(("", PORT), UpdateHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\n服务已停止')

if __name__ == '__main__':
    main()
