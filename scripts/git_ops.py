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

def cmd_checkout():
    """Silent checkout - clone or update repo without git console popup."""
    token = os.environ.get('GH_PAT', '')
    url = f'https://x-access-token:{token}@github.com/hintime/cs2-dashboard.git'
    if os.path.exists('.git'):
        print('[CHECKOUT] Repo exists, fetch + reset...')
        git('remote', 'set-url', 'origin', url)
        git('fetch', 'origin', 'main')
        git('reset', '--hard', 'origin/main')
        git('clean', '-fd')
    else:
        print('[CHECKOUT] Fresh clone...')
        git('clone', '--depth=1', url, '.')
        git('remote', 'set-url', 'origin', url)
    print('[CHECKOUT] Done')

def cmd_config():
    """Configure git user and remote."""
    token = os.environ.get('GH_PAT', '')
    git('config', 'user.email', 'hintime@users.noreply.github.com')
    git('config', 'user.name', 'hintime')
    git('config', 'core.askPass', '')
    git('config', 'credential.helper', '')
    if token:
        url = f'https://x-access-token:{token}@github.com/hintime/cs2-dashboard.git'
        git('remote', 'set-url', 'origin', url)
    print('[OK] Git configured')

def cmd_status():
    r = git('status', '--short')
    print(r.stdout or 'No changes')

def cmd_push():
    r = git('add', '-A')
    r = git('diff', '--cached', '--quiet')
    if r.returncode != 0:
        git('commit', '-m', 'chore: data update', '--allow-empty')
        for attempt in range(2):
            r = git('pull', '--rebase', 'origin', 'main')
            if r.returncode != 0:
                print('[WARN] Pull conflict, accepting remote...')
                git('rebase', '--abort')
                git('reset', '--hard', 'origin/main')
            r = git('push', 'origin', 'main')
            if r.returncode == 0:
                print('[OK] Push succeeded')
                return
            print(f'[WARN] Push attempt {attempt+1} failed')
        print('[ERROR] Push failed after 2 attempts')
    else:
        print('No changes to commit')

if __name__ == '__main__':
    cmds = {'config': cmd_config, 'status': cmd_status, 'push': cmd_push, 'checkout': cmd_checkout}
    if len(sys.argv) > 1 and sys.argv[1] in cmds:
        cmds[sys.argv[1]]()
    else:
        print(f'Usage: python {sys.argv[0]} <config|status|push>')
