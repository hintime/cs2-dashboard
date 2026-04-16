#!/usr/bin/env python3
"""Push market.json to GitHub via REST API using GITHUB_TOKEN."""
import os, json, base64, urllib.request, urllib.error

token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN', '')
repo = 'hintime/cs2-dashboard'
headers = {
    'Authorization': f'token {token}',
    'User-Agent': 'github-actions',
    'Accept': 'application/vnd.github.v3+json',
    'Content-Type': 'application/json'
}
ssl_ctx = __import__('ssl').create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = __import__('ssl').CERT_NONE

def get_sha(path):
    req = urllib.request.Request(
        f'https://api.github.com/repos/{repo}/contents/{path}',
        headers=headers
    )
    r = urllib.request.urlopen(req, timeout=15, context=ssl_ctx)
    return json.loads(r.read())['sha']

def update_file(path, msg):
    sha = None
    try:
        sha = get_sha(path)
        print(f'sha for {path}: {sha[:8]}')
    except Exception as e:
        print(f'get_sha error for {path}: {e} -- proceeding without sha')
    content_bytes = open(path, 'rb').read()
    b64 = base64.b64encode(content_bytes).decode('ascii')
    body = json.dumps({'message': msg, 'content': b64, 'sha': sha}).encode()
    req = urllib.request.Request(
        f'https://api.github.com/repos/{repo}/contents/{path}',
        data=body,
        headers=headers,
        method='PUT'
    )
    try:
        r = urllib.request.urlopen(req, timeout=15, context=ssl_ctx)
        result = json.loads(r.read())
        print(f'OK {path}: {result["commit"]["sha"][:8]}')
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()[:500]
        print(f'FAIL {path}: HTTP {e.code}: {err_body}')

ts = __import__('datetime').datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
update_file('market.json', f'chore: Auto-update prices {ts}')
print('All done.')
