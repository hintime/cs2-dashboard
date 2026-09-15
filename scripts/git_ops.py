#!/usr/bin/env python3
"""Silent git operations - no console windows on Windows."""
import subprocess, sys, os, time, random

def _flags():
    if sys.platform != 'win32':
        return 0
    return subprocess.CREATE_NO_WINDOW  # 0x08000000 - no console window at all

def _env():
    """Env for git calls.

    GIT_CONFIG_* injects `safe.directory = *` at the highest precedence level
    (above system/global/local config). Needed because the GitHub Actions
    self-hosted runner executes as NT AUTHORITY\\SYSTEM while the checkout
    directory is owned by the interactive user, which makes git >= 2.35.2
    abort with "detected dubious ownership in repository". Repo-local config
    is deliberately ignored by git for safe.directory, so we must use the
    environment channel (or a system-wide config, which needs admin rights).
    """
    return {
        **os.environ,
        'GIT_TERMINAL_PROMPT': '0',
        'GIT_ASKPASS': 'echo',
        'GIT_CONFIG_COUNT': '1',
        'GIT_CONFIG_KEY_0': 'safe.directory',
        'GIT_CONFIG_VALUE_0': '*',
    }


def git(*args):
    return subprocess.run(['git'] + list(args),
        capture_output=True, text=True, creationflags=_flags(), env=_env())

# Network ops on this machine reach GitHub through a local transparent proxy
# (hosts maps github.com -> 127.0.0.1) which returns transient 502s under load.
# A single flake used to kill the whole job, so retry with backoff.
TRANSIENT_MARKERS = ('502', '503', '504', 'timed out', 'Timeout', 'Connection reset',
                     'unexpected eof', 'early EOF', 'RPC failed', 'Recv failure',
                     'Could not resolve host', 'Empty reply from server')

def git_retry(args, attempts=5, base_delay=3.0, label=''):
    """Run a git command, retrying transient network failures."""
    last = None
    for i in range(attempts):
        r = git(*args)
        if r.returncode == 0:
            if i:
                print('[RETRY] %s succeeded on attempt %d' % (label or ' '.join(args), i + 1))
            return r
        blob = ((r.stderr or '') + (r.stdout or ''))
        transient = any(m in blob for m in TRANSIENT_MARKERS)
        last = r
        if not transient:
            return r                      # real error (auth, conflicts...) - don't retry
        if i < attempts - 1:
            delay = base_delay * (2 ** i) + random.uniform(0, 1.5)
            print('[RETRY] %s attempt %d/%d failed (transient), retry in %.1fs: %s'
                  % (label or ' '.join(args), i + 1, attempts, delay,
                     blob.strip().splitlines()[0][:120] if blob.strip() else '?'))
            time.sleep(delay)
    return last

def _token():
    return os.environ.get('GH_PAT', '') or os.environ.get('GH_TOKEN', '')

# Local artifacts that must survive `git clean`:
# price_history.db is a ~360 MB local price database that is intentionally
# NOT tracked in the remote repo (it lives only on the runner machine).
# A bare `git clean -fd` in a repo whose index is empty would wipe the whole
# working tree, so clean is now restricted to a safe, explicit scope.
CLEAN_KEEP = ['price_history.db', 'price_history.db-*', '*.db', '*.db-wal', '*.db-shm',
              'local_keys.env', 'logs', 'logs/*']

def _head_exists():
    """True if HEAD resolves to a commit (i.e. this is not a fresh empty repo)."""
    return git('rev-parse', '--verify', 'HEAD').returncode == 0

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
        # SHALLOW fetch, matching the original `clone --depth=1` behaviour.
        # This machine reaches GitHub through a slow local transparent proxy
        # (~25 KB/s observed). A full-history fetch would take hours and kept
        # timing out mid-transfer, so we only ever pull the single tip commit.
        # --deepen is attempted once if the shallow tip cannot be resolved.
        r = git_retry(['fetch', '--depth=1', '--no-tags', 'origin', 'main'],
                      label='fetch')
        if r.returncode != 0:
            print('[RETRY] shallow fetch failed, trying --deepen=1')
            r = git_retry(['fetch', '--deepen=1', '--no-tags', 'origin', 'main'],
                          label='fetch-deepen')
        if r.returncode != 0:
            print('[ERROR] fetch failed: ' + (r.stderr or '')[:300])
            sys.exit(1)
        # FETCH_HEAD is authoritative after a fetch; origin/main ref may not
        # exist in a repo that was only ever shallow-fetched.
        target = 'FETCH_HEAD'
        if git('rev-parse', '--verify', 'origin/main').returncode == 0:
            target = 'origin/main'
        rr = git('reset', '--hard', target)
        if rr.returncode != 0:
            print('[ERROR] reset failed: ' + (rr.stderr or '')[:300])
            sys.exit(1)
        # Only clean when the index is real. On an empty/just-initialised
        # repo every file is "untracked" and a plain clean -fd would delete
        # the entire working tree including the local price database.
        if _head_exists():
            clean_args = ['clean', '-fd']
            for keep in CLEAN_KEEP:
                clean_args += ['-e', keep]
            git(*clean_args)
        else:
            print('[CHECKOUT] empty index - skipping git clean (protects local data)')
    else:
        print('[CHECKOUT] Fresh clone...')
        r = git_retry(['clone', '--depth=1', '--no-tags', url, '.'], label='clone')
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
    r = git_retry(['pull', '--rebase', 'origin', 'main'], label='pull --rebase')
    if r.returncode != 0:
        # FIX: never discard freshly scraped data via reset --hard
        git('rebase', '--abort')
        print('[ERROR] pull --rebase failed, local data KEPT (not pushed): ' + (r.stderr or '')[:300])
        sys.exit(1)
    r = git_retry(['push', 'origin', 'main'], label='push')
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
