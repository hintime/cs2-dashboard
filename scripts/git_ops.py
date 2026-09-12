#!/usr/bin/env python3
"""Silent git operations - no console windows on Windows."""
import subprocess, sys, os

def _flags():
    if sys.platform != 'win32':
        return 0
    return subprocess.CREATE_NO_WINDOW  # 0x08000000 - no console window at all

def git(*args):
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': 'echo'}
    return subprocess.run(['git'] + list(args),
        capture_output=True, text=True, creationflags=_flags(), env=env)

def _token():
    return os.environ.get('GH_PAT', '') or os.environ.get('GH_TOKEN', '')

def cmd_checkout():
    """Silent checkout - clone or update repo without git console popup."""
    token = _token()
    if not token:
        print('[ERROR] No token (GH_PAT/GH_TOKEN empty) - aborting')
        sys.exit(1)
    url = f'https://x-access-token:{token}@github.com/hintime/cs2-dashboard.git'
    if os.path.exists('.git'):
        print('[CHECKOUT] Repo exists, fetch + reset...')
        git('remote', 'set-url', 'origin', url)
        r = git('fetch', 'origin', 'main')
        if r.returncode != 0:
            print('[ERROR] fetch failed: ' + (r.stderr or '')[:300])
            sys.exit(1)
        git('reset', '--hard', 'origin/main')
        git('clean', '-fd')
    else:
        print('[CHECKOUT] Fresh clone...')
        r = git('clone', '--depth=1', url, '.')
        if r.returncode != 0:
            print('[ERROR] clone failed: ' + (r.stderr or '')[:300])
            sys.exit(1)
        git('remote', 'set-url', 'origin', url)
    print('[CHECKOUT] Done')

def cmd_config():
    """Configure git user and remote."""
    token = _token()
    git('config', 'user.email', 'hintime@users.noreply.github.com')
    git('config', 'user.name', 'hintime')
    git('config', 'core.askPass', '')
    git('config', 'credential.helper', '')
    if token:
        url = f'https://x-access-token:{token}@github.com/hintime/cs2-dashboard.git'
        git('remote', 'set-url', 'origin', url)
    else:
        print('[WARN] token empty - remote url unchanged')
    print('[OK] Git configured')

def cmd_status():
    r = git('status', '--short')
    print(r.stdout or 'No changes')

def cmd_push():
    git('add', '-A')
    r = git('diff', '--cached', '--quiet')
    if r.returncode == 0:
        print('No changes to commit')
        return
    git('commit', '-m', 'chore: data update', '--allow-empty')
    r = git('pull', '--rebase', 'origin', 'main')
    if r.returncode != 0:
        # FIX: never discard freshly scraped data via reset --hard
        git('rebase', '--abort')
        print('[ERROR] pull --rebase failed, local data KEPT (not pushed): ' + (r.stderr or '')[:300])
        sys.exit(1)
    r = git('push', 'origin', 'main')
    if r.returncode != 0:
        print('[ERROR] push failed: ' + (r.stderr or '')[:300])
        sys.exit(1)
    print('[OK] Push succeeded')

if __name__ == '__main__':
    cmds = {'config': cmd_config, 'status': cmd_status, 'push': cmd_push, 'checkout': cmd_checkout}
    if len(sys.argv) > 1 and sys.argv[1] in cmds:
        cmds[sys.argv[1]]()
    else:
        print(f'Usage: python {sys.argv[0]} <config|status|push>')
